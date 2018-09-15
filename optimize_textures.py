import os
import re
import sys
import math
import time
import json
import random
import fnmatch

import signal
import traceback
import threading
import subprocess

import multiprocessing
import concurrent.futures

from string import Template

# FUNCTIONS

def scantree(path):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry)
        else:
            yield entry

def entries_calculate(tools, entries):
    for entry in entries:
        for tool in ['convert', 'texconv']:
            task = entry['task'][tool]
            params = task['params']
            info = info_dict[entry['subpath']]

            params['width'] = info['width']
            params['height'] = info['height']
            params['mipmaps'] = info['mipLevels']

            if 'ratio' in params:
                width = int(float(info['width']) * float(params['ratio']))
                height = int(float(info['height']) * float(params['ratio']))
                mipmaps = math.ceil(math.log(min(width, height), 2)) + 1
                params['width'] = width; params['height'] = height
                params['mipmaps'] = mipmaps
        yield entry

def files_enumerate(config, tools, path, files):
    for file in files:
        task = {}
        source = path
        destination = None
        subpath = os.path.relpath(file.path, path)
        for tool in tools:
            params = {}
            
            task[tool] = {}
            task[tool]['options'] = ''
            task[tool]['source'] = source
            task[tool]['params'] = params

            settings = config['tools'][tool]

            if 'destination' in settings:
                destination = settings['destination']
                task[tool]['destination'] = destination

            for recipe in config['recipes']:
                if fnmatch.fnmatch(subpath, recipe['pattern']):
                    if tool in recipe and 'options' in recipe[tool]:
                        for param in recipe[tool]:
                            if param not in ['options']:
                                params[param] = Template(str(recipe[tool][param])).safe_substitute(**params)
                        task[tool]['options'] = Template(recipe[tool]['options']).safe_substitute(**params)
                        
            source = destination

        yield {'subpath': subpath, 'task': task}

def tasks_execute(config, tool, entries, func, params):
    incremental = bool(config['incremental'])
    cpucount = max(1, multiprocessing.cpu_count() - 1)
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    max_workers = int(Template(str(config['tools'][tool]['threads'])).safe_substitute(cpucount = cpucount))
    config_file = os.path.join(scriptdir, '{}.json'.format(os.path.splitext(os.path.basename(__file__))[0]))
    config_file_stat = os.stat(config_file)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
        futures = []
        for entry in entries:
            source = None
            destination = None
            task = entry['task'][tool]
            subpath = entry['subpath']

            if 'source' in task:
                source = task['source']
                source_file = os.path.join(source, subpath)
                try:
                    source_file_stat = os.stat(source_file)
                except FileNotFoundError:
                    source_file_stat = None

            if 'destination' in task:
                destination = task['destination']
                destination_file = os.path.join(destination, subpath)
                try:
                    destination_file_stat = os.stat(destination_file)
                except FileNotFoundError:
                    destination_file_stat = None

            if incremental:
                if source and destination and config_file_stat and source_file_stat and destination_file_stat:
                    if not (source_file_stat.st_mtime > destination_file_stat.st_mtime or config_file_stat.st_mtime > destination_file_stat.st_mtime):
                        continue

            futures.append(executor.submit(func, config, entry, params))

        for future in concurrent.futures.as_completed(futures):
            yield future.result()

# WORKER TASKS

def texdiag_info_task(config, entry, params):
    result = {}

    verbose = bool(config['verbose'])

    subpath = entry['subpath']
    result['info_subpath'] = subpath

    task = entry['task']['info']
    options = task['options']; task_params = task['params']
    source = Template(task['source']).safe_substitute(**params)

    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)

    command_params = {'source': source, 'sourcepath': sourcepath, 'sourcedir': sourcedir, 'subpath': subpath, **task_params, **params}

    texdiag_command = Template(Template(config['tools']['info']['command']).safe_substitute(options = options, **command_params)).safe_substitute(**command_params)
    process = subprocess.Popen(texdiag_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
    if not verbose: 
        print("texdiag: " + subpath)
    else: 
        print("texdiag: " + texdiag_command)

    while True:
        stdout_line_newline = process.stdout.readline()
        stderr_line_newline = process.stderr.readline()
        stdout_line_no_newline = stdout_line_newline.rstrip()
        stderr_line_no_newline = stderr_line_newline.rstrip()
        if stdout_line_newline == '' and stderr_line_newline == '' and process.poll() is not None: break
        if stderr_line_no_newline:
            print('error: ' + stderr_line_no_newline)
        if stdout_line_no_newline:
            match = re.search(r'^\s*(\w[\w\s]+) = (.*)$', stdout_line_no_newline)
            if match:
                key = match.group(1); value = match.group(2)
                if key and value:
                    result[key] = value

    return result

def texconv_task(config, entry, params):
    debug = bool(config['debug'])
    verbose = bool(config['verbose'])

    subpath = entry['subpath']

    task = entry['task']['texconv']
    options = task['options']; task_params = task['params']
    source = Template(task['source']).safe_substitute(**params)
    destination = Template(task['destination']).safe_substitute(**params)

    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    destinationpath = os.path.join(destination, subpath); destinationdir = os.path.dirname(destinationpath)
    os.makedirs(destinationdir, exist_ok = True)

    command_params = {
        'sourcepath': sourcepath, 'sourcedir': sourcedir, 'destinationpath': destinationpath, 'destinationdir': destinationdir,
        'source': source, 'destination': destination, 'subpath': subpath, 'subdir': os.path.dirname(subpath), **task_params, **params
    }

    texconv_command = Template(Template(config['tools']['texconv']['command']).safe_substitute(options = options, **command_params)).safe_substitute(**command_params)
    process = subprocess.Popen(texconv_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
    if not verbose: 
        print("texconv: " + subpath)
    else: 
        print("texconv: " + texconv_command)

    while True:
        stdout_line_newline = process.stdout.readline()
        stderr_line_newline = process.stderr.readline()
        stdout_line_no_newline = stdout_line_newline.rstrip()
        stderr_line_no_newline = stderr_line_newline.rstrip()
        if stdout_line_newline == '' and stderr_line_newline == '' and process.poll() is not None: break
        if stdout_line_no_newline:
            match = re.search(r'FAILED', stdout_line_no_newline)
            if match:
                print('error: ' + stdout_line_no_newline)
            else:
                if debug: print('debug: ' + stdout_line_no_newline)
        if stderr_line_no_newline:
            print('error: ' + stderr_line_no_newline)

def convert_task(config, entry, params):
    debug = bool(config['debug'])
    verbose = bool(config['verbose'])

    subpath = entry['subpath']

    task = entry['task']['convert']
    options = task['options']; task_params = task['params']
    source = Template(task['source']).safe_substitute(**params)
    destination = Template(task['destination']).safe_substitute(**params)

    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    destinationpath = os.path.join(destination, subpath); destinationdir = os.path.dirname(destinationpath)
    os.makedirs(os.path.dirname(os.path.join(destination, subpath)), exist_ok = True)

    command_params = {
        'sourcepath': sourcepath, 'sourcedir': sourcedir, 'destinationpath': destinationpath, 'destinationdir': destinationdir,
        'source': source, 'destination': destination, 'subpath': subpath, 'subdir': os.path.dirname(subpath), **task_params, **params
    }

    convert_command =  Template(Template(config['tools']['convert']['command']).safe_substitute(options = options, **command_params)).safe_substitute(**command_params)
    process = subprocess.Popen(convert_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)

    if not verbose: 
        print("convert: " + subpath)
    else: 
        print("convert: " + convert_command)

    while True:
        stdout_line_newline = process.stdout.readline()
        stderr_line_newline = process.stderr.readline()
        stdout_line_no_newline = stdout_line_newline.rstrip()
        stderr_line_no_newline = stderr_line_newline.rstrip()
        if stdout_line_newline == '' and stderr_line_newline == '' and process.poll() is not None: break
        if stdout_line_no_newline:
            if debug: print('debug: ' + stdout_line_no_newline)
        if stderr_line_no_newline:
            print('error: ' + stderr_line_no_newline)

# MAIN
if __name__ == '__main__':

    paths = sys.argv[1:]
    scriptdir = os.path.dirname(os.path.realpath(__file__))

    config_file = os.path.join(scriptdir, '{}.json'.format(os.path.splitext(os.path.basename(__file__))[0]))
    with open(config_file, encoding='utf-8') as file:
        config = json.loads(file.read())

    for path in paths:
        path = os.path.realpath(path)
        files = [x for x in scantree(path) if x.is_file()]

        info_entries = files_enumerate(config, ['info'], path, files)
        info_list = tasks_execute(config, "info", info_entries, texdiag_info_task, {'scriptdir': scriptdir})
        info_dict = {x['info_subpath']: x for x in info_list}

        entries = files_enumerate(config, ['convert', 'texconv'], path, files)
        calculated_entries = entries_calculate(['convert'], entries)

        list(tasks_execute(config, "convert", calculated_entries, convert_task, {'scriptdir': scriptdir}))

        entries = files_enumerate(config, ['convert', 'texconv'], path, files)
        calculated_entries = entries_calculate(['texconv'], entries)

        list(tasks_execute(config, "texconv", calculated_entries, texconv_task, {'scriptdir': scriptdir}))