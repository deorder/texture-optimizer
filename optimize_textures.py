import os
import re
import sys
import math
import time
import json
import copy
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

def destination_outofdate_test(source_files, destination_file):
    try:
        destination_file_stat = os.stat(destination_file)
    except FileNotFoundError:
        return True
    source_file_stats = [os.stat(x) for x in source_files]
    return any(map(lambda x: x.st_mtime > destination_file_stat.st_mtime, source_file_stats))

# GENERATORS

def scantree_generator(path, root = None):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks = False):
            yield from scantree_generator(entry, path)
        else:
            subpath = os.path.relpath(entry.path, root or path)
            yield {'subpath': subpath, 'path': entry.path}

def entries_calculate_generator(infos, entries):
    for entry in entries:
        result = copy.copy(entry)
        if 'params' in entry:
            info = infos[entry['subpath']]
            params = result['params'] = copy.copy(entry['params'])

            params['width'] = info['width']
            params['height'] = info['height']
            params['mipmaps'] = info['mipLevels']

            if 'ratio' in params:
                width = int(float(info['width']) * float(params['ratio']))
                height = int(float(info['height']) * float(params['ratio']))
                mipmaps = math.ceil(math.log(min(width, height), 2)) + 1
                params['width'] = width; params['height'] = height
                params['mipmaps'] = mipmaps

        yield result

def entries_enumerate_generator(toolname, recipes, entries):
    for entry in entries:
        params = {}
        result = {}

        result['options'] = ''
        result['params'] = params

        subpath = result['subpath'] = entry['subpath']

        for recipe in recipes:
            if fnmatch.fnmatch(subpath, recipe['pattern']):
                if toolname in recipe and 'options' in recipe[toolname]:
                    for param in recipe[toolname]:
                        if param not in ['options']:
                            params[param] = Template(str(recipe[toolname][param])).safe_substitute(**params)
                    result['options'] = Template(recipe[toolname]['options']).safe_substitute(**params)

        yield result

# WORKER TASKS

def info_task(config, source, entry, params):
    info = {}

    subpath = entry['subpath']
    options = entry['options']
    task_params = entry['params']

    verbose = bool(config['verbose'])
    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)

    command_params = {'source': source, 'sourcepath': sourcepath, 'sourcedir': sourcedir, 'subpath': subpath, **task_params, **params}

    texdiag_command = Template(config['tools']['info']['command']).safe_substitute(options = Template(options).safe_substitute(**command_params), **command_params)
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
                    info[key] = value

    return {'subpath': subpath, 'info': info}

def texconv_task(config, source, destination, entry, params):
    debug = bool(config['debug'])
    verbose = bool(config['verbose'])

    subpath = entry['subpath']
    options = entry['options']
    task_params = entry['params']
    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    destinationpath = os.path.join(destination, subpath); destinationdir = os.path.dirname(destinationpath)

    os.makedirs(destinationdir, exist_ok = True)

    command_params = {
        'sourcepath': sourcepath, 'sourcedir': sourcedir, 'destinationpath': destinationpath, 'destinationdir': destinationdir,
        'source': source, 'destination': destination, 'subpath': subpath, 'subdir': os.path.dirname(subpath), **task_params, **params
    }

    texconv_command = Template(config['tools']['texconv']['command']).safe_substitute(options = Template(options).safe_substitute(**command_params), **command_params)
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

def convert_task(config, source, destination, entry, params):
    debug = bool(config['debug'])
    verbose = bool(config['verbose'])

    subpath = entry['subpath']
    options = entry['options']
    task_params = entry['params']
    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    destinationpath = os.path.join(destination, subpath); destinationdir = os.path.dirname(destinationpath)

    os.makedirs(os.path.dirname(os.path.join(destination, subpath)), exist_ok = True)

    command_params = {
        'sourcepath': sourcepath, 'sourcedir': sourcedir, 'destinationpath': destinationpath, 'destinationdir': destinationdir,
        'source': source, 'destination': destination, 'subpath': subpath, 'subdir': os.path.dirname(subpath), **task_params, **params
    }

    convert_command = Template(config['tools']['convert']['command']).safe_substitute(options = Template(options).safe_substitute(**command_params), **command_params)
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
    cpucount = max(1, multiprocessing.cpu_count() - 1)
    scriptdir = os.path.dirname(os.path.realpath(__file__))

    config_file = os.path.join(scriptdir, '{}.json'.format(os.path.splitext(os.path.basename(__file__))[0]))
    with open(config_file, encoding='utf-8') as file:
        config = json.loads(file.read())

    for path in paths:
        path = os.path.realpath(path)
        params = {'scriptdir': scriptdir}

        files = list(scantree_generator(path))

        infos = {}
        source = path
        entries = entries_enumerate_generator('info', config['recipes'], files)
        max_workers = int(Template(str(config['tools']['info']['threads'])).safe_substitute(cpucount = cpucount))
        with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
            futures = []
            for entry in entries:
                futures.append(executor.submit(info_task, config, source, entry, {**params}))
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                infos[result['subpath']] = result['info']

        source = path
        destination = Template(config['tools']['convert']['destination']).safe_substitute(**params)
        entries = entries_enumerate_generator('convert', config['recipes'], files)
        calculated_entries = entries_calculate_generator(infos, entries)

        with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
            futures = []
            for entry in calculated_entries:
                source_files = [
                    config_file,
                    os.path.join(source, entry['subpath'])
                ]
                destination_file = os.path.join(destination, entry['subpath'])
                if not destination_outofdate_test(source_files, destination_file): continue
                futures.append(executor.submit(convert_task, config, source, destination, entry, {**params}))
            for future in concurrent.futures.as_completed(futures):
                pass

        source = destination
        destination = Template(config['tools']['texconv']['destination']).safe_substitute(**params)
        entries = entries_enumerate_generator('texconv', config['recipes'], files)
        calculated_entries = entries_calculate_generator(infos, entries)

        with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
            futures = []
            for entry in calculated_entries:
                source_files = [
                    config_file,
                    os.path.join(source, entry['subpath'])
                ]
                destination_file = os.path.join(destination, entry['subpath'])
                if not destination_outofdate_test(source_files, destination_file): continue
                futures.append(executor.submit(texconv_task, config, source, destination, entry, {**params}))
            for future in concurrent.futures.as_completed(futures):
                pass
