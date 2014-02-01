#/usr/bin/env python3

"""Squid Arduino toolkit by Michael Sproul, Copyright 2014.
Licensed under the terms of the GNU GPLv3+
See: https://www.gnu.org/licenses/gpl.html
"""

import os
import re
import sys
import glob
import argparse
import subprocess
import configparser

from squid.dependencies import dependency_map

config = {}

# Find the squid installation directory
squid_root = sys.modules[__name__].__file__
squid_root = os.path.realpath(squid_root)
squid_root = os.path.dirname(squid_root)

os.environ["PATH"] += ":" + squid_root

def read_config():
	"""Read squid config from ~/.squidrc and .squid

	Values in .squid override those in ~/.squidrc
	"""
	parser = configparser.ConfigParser()

	# Load defaults
	defaults = {"squid": {	"arduino_root": "/usr/share/arduino",
				"arduino_ver": "",
				"compile_root": "~/.squid/"
	}}
	parser.read_dict(defaults)

	# Read ~/.squidrc
	squidrc = os.path.expanduser("~/.squidrc")
	if os.path.exists(squidrc):
		parser.read(squidrc)

	# Read .squid
	dotsquid = os.path.abspath(".squid")
	if os.path.exists(dotsquid):
		parser.read(dotsquid)

	config = dict(parser["squid"])

	# Expand paths
	config["arduino_root"] = os.path.expanduser(config["arduino_root"])
	config["compile_root"] = os.path.expanduser(config["compile_root"])

	# Figure out software version
	if config["arduino_ver"] == "":
		config["arduino_ver"] = read_arduino_ver(config["arduino_root"])
	else:
		# Convert the version to an integer
		config["arduino_ver"] = int(config["arduino_ver"].replace(".", ""))

	return config


def read_arduino_ver(arduino_root):
	"""Extract the Arduino software version from the given root directory."""
	version_path = os.path.join(arduino_root, "lib", "version.txt")
	if not os.path.isfile(version_path):
		print("Unable to find version.txt, please specify version in ~/.squidc or .squid")
		sys.exit(1)

	with open(version_path, "r") as version_file:
		version = version_file.read().strip()
	try:
		version = int(version.replace(".", ""))
		return version
	except ValueError:
		print("Unable to parse version number, please specify version in ~/.squidrc or .squid")
		sys.exit(1)


def read_boards():
	"""Parse boards.txt and return a dictionary."""
	boards = {}
	arduino_root = config['arduino_root']
	arduino_ver = config['arduino_ver']

	if arduino_ver < 150:
		filepath = "hardware/arduino/boards.txt"
	else:
		filepath = "hardware/arduino/avr/boards.txt"
	filepath = os.path.join(arduino_root, filepath)
	f = open(filepath, "r")
	for line in f:
		if line[0] in "\n#":
			continue

		(key, value) = line.strip().split("=")
		key = key.split(".")
		board = key[0]
		property = ".".join(key[1:])
		if board not in boards:
			boards[board] = {}
		boards[board][property] = value

	f.close()
	return boards


# ----------------------------------------------------- #
#			Commands			#
# ----------------------------------------------------- #

def init(args):
	"""Create a new project makefile from the template.

	The makefile will be created in the current directory, or the
	directory specified by the `dir' argument to `squid init'.

	The makefile will be named Makefile and will not be created if
	a file with this name already exists.
	"""
	# Check for an existing Makefile
	project_dir = os.path.abspath(args.dir)
	makefile_path = os.path.join(project_dir, "Makefile")
	if os.path.exists(makefile_path):
		if args.dir == ".":
			print("Error: Makefile exists!")
		else:
			print("Error: %s exists!" % makefile_path)
		sys.exit(1)

	# Read boards.txt
	boards = read_boards()

	# Request a project name
	project = ""
	while project == "":
		project = input("Project name: ").strip()

	# Request a board to compile for
	print("Please select a board: ")
	_list_boards(boards)
	while True:
		board = input("Board short name: ").strip()
		if board in boards:
			break
		print("Invalid. Please pick a board (you can change later).")

	# Inject the board and project name into the makefile template
	template_path = os.path.join(squid_root, "Project.mk")
	template_file = open(template_path, "r")
	makefile = template_file.read()
	makefile = makefile.replace("{PROJECT}", project).replace("{BOARD}", board)

	# Write the makefile
	with open(makefile_path, "w") as file:
		file.write(makefile)

	print("Successfully created a new makefile.")


def list_boards(args):
	"""List all available boards from boards.txt"""
	boards = read_boards()
	_list_boards(boards)


def _list_boards(boards):
	"""Pretty print a list of boards in alphabetical order."""
	board_names = sorted(boards.keys(), key=lambda x: x.lower())
	for board in board_names:
		spacer = "\t\t" if len(board) < 8 else "\t"
		print("%s%s'%s'" % (board, spacer, boards[board]["name"]))


def get_property(args):
	"""Print the board property requested on the command-line.

	A property is just a bit of information from the Arduino library's
	collection of hardware specific information - "boards.txt".

	Throughout Imp, the names from "boards.txt" are split into a
	board name and a "property".

	Example:
	If the board is "atmega328" and property is "build.f_cpu"
	the value of "atmega328.build.f_cpu" will be fetched.
	"""
	boards = read_boards()
	key = args.property.split(".")
	board = key[0]
	subprop = ".".join(key[1:])
	print(boards[board][subprop])


def get_cflags(args):
	"""Print the C compiler flags for the given board."""
	boards = read_boards()
	cflags = _get_cflags(args.board, boards)
	print(cflags)


def _get_cflags(board, boards):
	"""Get the C compiler flags for the given board."""
	board_info = boards[board]
	flags = "-mmcu=%(build.mcu)s -DF_CPU=%(build.f_cpu)s" % board_info
	flags += " -DARDUINO=%s" % config["arduino_ver"]
	return flags


def get_src(args):
	"""Print a list of source directories for the requested libraries.

	The list items can optionally be separated by -I to form a string
	suitable for appending to GCC. Dependencies not included.
	"""
	# If the board argument is provided, read boards.txt to get variant
	if args.board:
		boards = read_boards()
		variant = boards[args.board]["build.variant"]
	else:
		variant = "standard"

	# Get the list of libraries
	libraries = args.libraries

	# Automatically include the core library
	if "core" not in libraries:
		libraries.append("core")

	# Fetch the source code directories
	src_dirs = _get_src(libraries, variant)

	if args.dash_i:
		output = "-I " + " -I ".join(src_dirs)
	else:
		output = " ".join(src_dirs)

	print(output)


def _get_src(libraries, variant):
	"""Return a list of directories containing relevant source code.

	By relevant source code, we mean source code for those libraries listed
	in the `libraries' argument (a list). The core Arduino library is
	not included unless "core" is amongst the list of libraries.

	If the core library is requested, "variant" is the type of
	Arduino board to compile for. Most boards are just "standard".
	"""
	src_dirs = []
	root = config["arduino_root"]

	# Sub-function to get the core library
	def get_core():
		core = os.path.join(root, "hardware/arduino/cores/arduino")
		core_sub_dirs = glob.glob("%s/*/" % core)
		var_dir = os.path.join(root, "hardware/arduino/variants/%s" % variant)
		return core_sub_dirs + [core, var_dir]

	# Add requested libraries
	for lib in libraries:
		# Treat the core library carefully
		if lib == "core":
			src_dirs.extend(get_core())
			continue

		# Look in libraries/name otherwise
		lib_main = os.path.join(root, "libraries/%s" % lib)
		src_dirs.append(lib_main)

		lib_util = os.path.join(lib_main, "utility")
		if os.path.exists(lib_util):
			src_dirs.append(lib_util)

	return src_dirs


def get_obj(args):
	"""Print the names of all the .o files for a given library."""
	library = args.library

	# Convert the library name into a list of directories
	if library == "core":
		# XXX: This takes advantage of the fact that the variant
		# folders only include headers. Might need to be updated.
		library_dirs = _get_src(["core"], "standard")
	else:
		library_dirs = _get_src([args.library], "n/a")

	objects = _get_obj(library_dirs)
	print(" ".join(objects))


def _get_obj(library_dirs):
	"""Get the names of all the .o files in the given directories."""
	# Filter functions, to turn source filepaths into object filenames
	c_filter = lambda x: x.split("/")[-1].replace(".c", ".o")
	cpp_filter = lambda x: x.split("/")[-1].replace(".cpp", ".o")

	# Find objects for each directory in the input
	objects = []
	for directory in library_dirs:
		c_files = glob.glob("%s/*.c" % directory)
		objects.extend([c_filter(x) for x in c_files])
		cpp_files = glob.glob("%s/*.cpp" % directory)
		objects.extend([cpp_filter(x) for x in cpp_files])

	return objects


def resolve_dependencies(libraries):
	"""Given a list of libraries, determine all of their dependencies.

	Return a list of the original libraries, plus their dependencies, ordered
	such that each library comes before all of its dependencies (a topological sort).
	"""
	# For each library store out-links (to dependencies) and in-links (from dependencies)
	graph = {}
	active_pool = {lib for lib in libraries}
	while len(active_pool) > 0:
		new_pool = set()
		for lib in active_pool:
			# Fetch the set of dependencies
			if lib in dependency_map:
				dependencies = dependency_map[lib]
			else:
				dependencies = set()

			# Add the implicit dependency on the core library
			if lib != "core" and lib != "math":
				dependencies.add("core")

			# Add the library to the graph
			if lib in graph:
				graph[lib]["out"] = dependencies
			else:
				graph[lib] = {"in": set(), "out": dependencies}

			# Add each dependency to the graph and the active pool if need be
			for dep in dependencies:
				if dep in graph:
					graph[dep]["in"].add(lib)
				else:
					graph[dep] = {"in": {lib}, "out": set()}
					new_pool.add(dep)
		active_pool = new_pool

	# Perform a topological sort on the graph
	library_list = []
	no_inlinks = {node for node in graph if len(graph[node]["in"]) == 0}
	while len(no_inlinks) > 0:
		node = no_inlinks.pop()
		library_list.append(node)

		# Remove it from the graph
		for dep in graph[node]["out"]:
			graph[dep]["in"].remove(node)
			if len(graph[dep]["in"]) == 0:
				no_inlinks.add(dep)
		del graph[node]

	# Check for success
	if len(graph) == 0:
		return library_list
	else:
		print("Error: Cyclic dependencies!")
		sys.exit(1)


def get_lib(args):
	"""Print a list of folders containing the requested libraries, compiled.

	The libraries are either compiled from scratch or fetched from the
	cache that accumulates in config['compile_root'].
	"""
	boards = read_boards()
	board = args.board
	libraries = args.libraries

	# Add the core library if it isn't present
	if "core" not in libraries:
		libraries.append("core")

	# Make
	library_list, output = _get_lib(libraries, board, boards)

	if args.verbose:
		for lib in output:
			print("-- Output from %s make command --" % lib)
			print(output[lib])

	if args.dash_big_l:
		library_string = "-L " + " -L ".join(library_list)
	else:
		library_string = " ".join(library_list)

	if args.dash_little_l:
		# Extract library names (dependencies could have been added)
		lib_names = [x.split("/")[-1] for x in library_list]

		# Add the math library, if required
		for lib in lib_names:
			if lib in math_libs:
				lib_names.append("m")
				break

		# Lowercase all library names to match the archives
		lib_names = [lib.lower() for lib in lib_names]

		# Create the library string
		library_string += " -l" + " -l".join(lib_names)

	print(library_string)


def _get_lib(libraries, board, boards):
	"""Make each library in compile_root/board/library.

	Return a list of directories containing compiled versions.
	Dependecies are compiled and have their folders included.
	"""
	# Resolve dependencies (using sets & BFS style search)
	active_pool = {lib for lib in libraries}
	libraries = set()
	while len(active_pool) > 0:
		new_pool = set()
		for lib in active_pool:
			if lib in dependencies:
				new_libs = dependencies[lib].difference(libraries)
				new_libs = new_libs.difference(active_pool)
				new_pool.update(new_libs)
			libraries.add(lib)
		active_pool = new_pool

	# Set up environment variables for each make instance
	env = {lib: {"LIBRARY": lib} for lib in libraries}

	# Set up a dictionary of make processes
	makes = {lib: None for lib in libraries}

	# Set up the list of directories to return
	library_list = []

	# Set up common arguments
	cflags = _get_cflags(board, boards)
	variant = boards[board]["build.variant"]
	core_src = _get_src(["core"], variant)

	for lib in env:
		# Set common variables
		env[lib]["BOARD"] = board
		env[lib]["BOARD_C_FLAGS"] = cflags
		env[lib]["PATH"] = os.environ["PATH"]

		# Set library specific variables
		if lib == "core":
			lib_src = core_src
			lib_obj = _get_obj(lib_src)
		else:
			# Add the main source folders for the library
			lib_src = _get_src([lib], variant)
			lib_obj = _get_obj(lib_src)
			lib_src.extend(core_src)

			# Include dependency source folders
			if lib in dependencies:
				dep_src = _get_src(dependencies[lib], "n/a")
				lib_src.extend(dep_src)

		env[lib]["SRC_DIRS"] = " ".join(lib_src)
		env[lib]["INCLUDES"] = "-I" + " -I ".join(lib_src)
		env[lib]["LIBOBJS"] = " ".join(lib_obj)

		# Set the compilation directory
		compile_dir = os.path.join(config["compile_root"], "%s/%s" % (board, lib))
		try:
			os.makedirs(compile_dir, mode=0o0775, exist_ok=True)
		except OSError:
			pass
		library_list.append(compile_dir)

		# Find the makefile to use
		makefile = os.path.join(squid_root, "libraries/%s.mk" % lib)
		if not os.path.exists(makefile):
			makefile = os.path.join(squid_root, "Library.mk")

		# Run make in a subprocess
		make_args = ["make", "-f", makefile]
		makes[lib] = subprocess.Popen(make_args, cwd=compile_dir, env=env[lib],
						stdout=subprocess.PIPE, stderr=subprocess.PIPE)

	# Wait for make processes to finish and collect output
	error = False
	output = {}
	for lib in makes:
		returncode = makes[lib].wait()
		stdout, stderr = makes[lib].communicate()
		output[lib] = stdout.decode()

		if returncode != 0:
			error = True
			output[lib] += stderr.decode()

	if error:
		for lib in output:
			print("-- Output from %s make command --" % lib)
			print(output[lib])
		print("Fatal error, unable to compile all libraries.")
		sys.exit(1)

	return (library_list, output)


def make(args):
	"""Make the project in the current directory, using its Makefile.

	This function "pre-fills" all squid variables to avoid multiple calls.
	"""
	# Check for makefile existence
	if not os.path.isfile("Makefile"):
		print("No Makefile in the current directory.")
		print("Run `squid init` to get one.")
		sys.exit(1)

	# Attempt to get the BOARD & LIBRARIES variables from the shell environment
	board = None
	libraries = None
	if "BOARD" in os.environ:
		board = os.environ["BOARD"]
	if "LIBRARIES" in os.environ:
		libraries = os.environ["LIBRARIES"]

	# Otherwise read them from the makefile
	makefile = None
	if board is None or libraries is None:
		makefile = open("Makefile", "r")
		board_regex =  re.compile(r"^BOARD\s*=(?P<value>[^#]*).*$")
		lib_regex = re.compile(r"^LIBRARIES\s*=(?P<value>[^#]*).*$")

	while board is None or libraries is None:
		line = makefile.readline()
		if line == "":
			print("Unable to extract BOARDS & LIBRARIES from makefile due to EOF.")
			sys.exit(1)

		if board is None:
			match = board_regex.match(line)
			if match:
				board = match.group("value").strip()

		if libraries is None:
			match = lib_regex.match(line)
			if match:
				libraries = match.group("value").strip()
	if makefile is not None:
		makefile.close()

	# Turn libraries into a list
	libraries = libraries.split(" ")

	# If libraries is empty, make it the empty list
	if libraries == [""]:
		libraries = []

	# Read boards.txt
	boards = read_boards()

	# Get the compiler flags
	cflags = _get_cflags(board, boards)

	# Get the source directories & header includes
	variant = boards[board]["build.variant"]
	libraries.append("core")
	src_dirs = _get_src(libraries, variant)
	header_includes = "-I " + " -I ".join(src_dirs)
	src_dirs = " ".join(src_dirs)

	# Make the libraries
	print("Making libraries...")
	lib_dirs, output = _get_lib(libraries, board, boards)

	# Print make output, so the user knows what's going on
	for lib in output:
		print("-- Output from %s make command --" % lib)
		print(output[lib])

	# Make the full library include string
	lib_includes = " -L " + " -L ".join(lib_dirs)
	lib_names = [x.split("/")[-1].lower() for x in lib_dirs]
	lib_includes += " -l" + " -l".join(lib_names)

	# Make the actual project
	env = { "BOARD_C_FLAGS": cflags,
		"SRC_DIRS": src_dirs,
		"HEADER_INCLUDES": header_includes,
		"LIB_INCLUDES": lib_includes,
		"PATH": os.environ["PATH"]
	}
	# XXX: Should we pass all of os.environ?

	make = subprocess.Popen(["make"], env=env)
	returncode = make.wait()
	if returncode == 0:
		print("Success!")
	else:
		print("Oh no! Make failed :(")
		sys.exit(1)


class CustomParser(argparse.ArgumentParser):
	"""Argument parser that prints a help message upon erroring."""
	def error(self, message):
		self.print_help()
		print("\nerror: %s" % message)
		sys.exit(1)


def setup_argparser():
	# Top level parser
	parser = CustomParser(prog="squid")
	subparsers = parser.add_subparsers()

	# Help strings
	h_init = "Create a new Arduino project"
	h_init_dir = "The directory in which to create the new project"
	h_list = "List all available boards"
	h_make = "Make the project in the current directory, quickly."
	h_get = "Get compiler flags, compiled libraries, etc"
	h_gprop1= "Get board properties from boards.txt"
	h_gprop2 = "The name of the property as it appears in boards.txt\n" \
		  "E.g. atmega328.build.f_cpu"
	h_board = "The short name of your Arduino board.\n" \
		  "Run `squid list` for a list."
	h_cflags = "Get the compiler flags for a specific board"
	h_src = "Get a list of directories containing library source code."
	h_src_libs = "A list of libraries to get source directories for."
	h_dash_i = "Add a -I before each directory (see gcc's -I option)."

	h_obj = "Get the names of all the .o files for a library."
	h_obj_lib = "The name of the library."

	h_lib = "Get the location(s) of compiled libraries"
	h_lib_libs = "A list of libraries to obtain compiled version of."
	h_dash_big_l = "Add a -L before each directory (see gcc's -L option)."
	h_dash_little_l = "Add a list of compiled archive names beginning with -l\n"\
			  "For example: -lcore -lethernet -lspi"

	# Parser for `squid init`
	init_parser = subparsers.add_parser("init", help=h_init)
	init_parser.add_argument("dir", nargs="?", default=".", help=h_init_dir)
	init_parser.set_defaults(func=init)

	# Parser for `squid list`
	list_parser = subparsers.add_parser("list", help=h_list)
	list_parser.set_defaults(func=list_boards)

	# Parser for `squid make`
	make_parser = subparsers.add_parser("make", help=h_make)
	make_parser.set_defaults(func=make)

	# Parser for `squid get`
	get_parser = subparsers.add_parser("get", help=h_get)
	get_subparsers = get_parser.add_subparsers()

	# Parser for `squid get property`
	property_parser = get_subparsers.add_parser("property", help=h_gprop1)
	property_parser.add_argument("property", help=h_gprop2)
	property_parser.set_defaults(func=get_property)

	# Parser for `squid get cflags`
	cflags_parser = get_subparsers.add_parser("cflags", help=h_cflags)
	cflags_parser.add_argument("board", help=h_board)
	cflags_parser.set_defaults(func=get_cflags)

	# Parser for `squid get src`
	src_parser = get_subparsers.add_parser("src", help=h_src)
	src_parser.add_argument("libraries", nargs="*", help=h_src_libs)
	src_parser.add_argument("--board", default=None, help=h_board)
	src_parser.add_argument("-I", dest="dash_i", action="store_true", help=h_dash_i)
	src_parser.set_defaults(func=get_src)

	# Parser for `squid get obj`
	obj_parser = get_subparsers.add_parser("obj", help=h_obj)
	obj_parser.add_argument("library", help=h_obj_lib)
	obj_parser.set_defaults(func=get_obj)

	# Parser for `squid get lib`
	lib_parser = get_subparsers.add_parser("lib", help=h_lib)
	lib_parser.add_argument("libraries", nargs="*", help=h_lib_libs)
	lib_parser.add_argument("--board", required=True, help=h_board)
	lib_parser.add_argument("-L", dest="dash_big_l", action="store_true", help=h_dash_big_l)
	lib_parser.add_argument("-l", dest="dash_little_l", action="store_true",
								help=h_dash_little_l)
	lib_parser.add_argument("-v", "--verbose", action="store_true")
	lib_parser.set_defaults(func=get_lib)

	return parser

def main():
	# Parse args
	parser = setup_argparser()
	args = parser.parse_args()

	# If no command has been given, bail out
	if not hasattr(args, "func"):
		parser.print_help()
		return

	# Read config & execute the command
	global config
	config = read_config()
	args.func(args)


if __name__ == "__main__":
	main()