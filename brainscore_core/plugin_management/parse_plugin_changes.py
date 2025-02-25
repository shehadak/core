import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Dict

from .test_plugins import run_args

PLUGIN_DIRS = ['models', 'benchmarks', 'data', 'metrics']


def separate_plugin_files(files: List[str]) -> Tuple[List[str], List[str]]:
	"""
	:return: one list of files that are located inside a plugin, and one list of files that are located outside of all plugins, 
		e.g. `['models/mymodel/__init__.py', 'models/mymodel/model.py', 'models/mymodel/test.py'], ['model_helpers/make_model_brainlike.py']`
	"""
	plugin_files = []
	non_plugin_files = []

	for f in files:
		subdir = f.split('/')[1] if len(f.split('/')) > 1 else None
		if not any(plugin_dir == subdir for plugin_dir in PLUGIN_DIRS):
			non_plugin_files.append(f)
		else:
			plugin_files.append(f)

	return plugin_files, non_plugin_files


def _plugin_name_from_path(path_relative_to_library: str) -> str:
    """
    Returns the name of the plugin from the given path. 
    E.g. `_plugin_name_from_path("brainscore_vision/models/mymodel")` will return `"mymodel"`.
    """
    return path_relative_to_library.split('/')[2]


def get_plugin_paths(plugin_files: List[str], domain_root: str) -> Dict[str, List[str]]:
	"""
	Returns a dictionary `plugin_type -> plugin names` with the full names of all plugin directories for each plugin_type
	"""
	plugins = {}
	for plugin_type in PLUGIN_DIRS:
		plugin_type_path = f'{domain_root}/{plugin_type}/'
		plugin_paths = [fpath for fpath in plugin_files if fpath.startswith(plugin_type_path)]
		plugins[plugin_type] = list(set([_plugin_name_from_path(fname) 
			for fname in plugin_paths if f'/{plugin_type}/' in fname]))
	return plugins


def get_plugin_ids(plugin_type: str, new_plugin_dirs: List[str], domain_root: str) -> List[str]:
	"""
	Searches all __init.py__ files in `new_plugin_dirs` of `plugin_type` for registered plugins.
	Returns list of identifiers for each registered plugin.
	"""
	plugin_ids = []

	for plugin_dirname in new_plugin_dirs:
		init_file = Path(f'{domain_root}/{plugin_type}/{plugin_dirname}/__init__.py')
		with open(init_file) as f:
			registry_name = plugin_type.strip(
				's') + '_registry'  # remove plural and determine variable name, e.g. "models" -> "model_registry"
			plugin_registrations = [line for line in f if f"{registry_name}["
									in line.replace('\"', '\'')]
			for line in plugin_registrations:
				result = re.search(f'{registry_name}\[.*\]', line)
				identifier = result.group(0)[len(registry_name) + 2:-2] # remove brackets and quotes
				plugin_ids.append(identifier)

	return plugin_ids


def parse_plugin_changes(changed_files: str, domain_root: str) -> dict:
	"""
	Return information about which files changed by the invoking PR (compared against main) belong to plugins

	:param commit_SHA: SHA of the invoking PR
	:param domain_root: the root package directory of the repo where the PR originates, either 'brainscore' (vision) or 'brainscore_language' (language)
	"""
	changed_files_list = changed_files.split()
	changed_plugin_files, changed_non_plugin_files = separate_plugin_files(changed_files_list)	

	plugin_info_dict = {}
	plugin_info_dict["modifies_plugins"] = False if len(changed_plugin_files) == 0 else True
	plugin_info_dict["changed_plugins"] = get_plugin_paths(changed_plugin_files, domain_root)
	plugin_info_dict["is_automergeable"] = len(changed_non_plugin_files) == 0

	return plugin_info_dict


def get_scoring_info(changed_files: str, domain_root: str):
	"""
	If any model or benchmark files changed, get plugin ids and set run_score to "True".
	Otherwise set to "False".
	Print all collected information about plugins.
	"""
	plugin_info_dict = parse_plugin_changes(changed_files, domain_root)

	scoring_plugin_types = ("models", "benchmarks")
	plugins_to_score = [plugin_info_dict["changed_plugins"][plugin_type] for plugin_type in scoring_plugin_types]

	if any(plugins_to_score):
		plugin_info_dict["run_score"] = "True"
		for plugin_type in scoring_plugin_types:
			scoring_plugin_ids = get_plugin_ids(plugin_type, plugin_info_dict["changed_plugins"][plugin_type], domain_root)
			plugin_info_dict[f'new_{plugin_type}'] = ' '.join(scoring_plugin_ids)
	else:
		plugin_info_dict["run_score"] = "False"

	print(plugin_info_dict) # output is accessed via print!


def get_testing_info(changed_files: str, domain_root: str):
	"""
	1. Print "true" if PR changes ANY plugin files, else print "false"
	2. Print "true" if PR ONLY changes plugin files, else print "false"
	"""
	plugin_info_dict = parse_plugin_changes(changed_files, domain_root)

	print(f'{plugin_info_dict["modifies_plugins"]} {plugin_info_dict["is_automergeable"]}', end="") # output is accessed via print!


def run_changed_plugin_tests(changed_files: str, domain_root: str):
	"""
	Initiates run of all tests in each changed plugin directory
	"""
	plugin_info_dict = parse_plugin_changes(changed_files, domain_root)

	if plugin_info_dict["modifies_plugins"]:
		tests_to_run = []
		for plugin_type in plugin_info_dict["changed_plugins"]:
			changed_plugins = plugin_info_dict["changed_plugins"][plugin_type]
			for plugin_dirname in changed_plugins:
				root = Path(f'{domain_root}/{plugin_type}/{plugin_dirname}')
				for filepath in root.rglob(r'test*.py'):
					tests_to_run.append(str(filepath))

		print(f"Running tests for new or modified plugins: {tests_to_run}")
		print(run_args(domain_root, tests_to_run)) # print tests to travis log

	else:
		print("No plugins changed or added.")
