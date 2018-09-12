import os
import re
import math
import random
import sys, time

import signal
import traceback
import threading
import subprocess

import configparser
import multiprocessing
import concurrent.futures

# FUNCTIONS

def scantree(path):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry)
        else:
            yield entry

def tasks_execute(config, section, entries, func, context):
    result = []
    cpucount = max(1, multiprocessing.cpu_count() - 1)
    incremental = bool(config.get("DEFAULT", "incremental"))
    max_workers = int(config.get(section, "threads").format(cpucount = cpucount))
    config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), '{}.cfg'.format(os.path.splitext(os.path.basename(__file__))[0]))
    config_file_stat = os.stat(config_file)
    with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
        futures = []
        try:
            source = config.get(section, "source").format(**context)
        except configparser.NoOptionError:
            source = None
        try:
            destination = config.get(section, "destination").format(**context)
        except configparser.NoOptionError:
            destination = None
        for entry in entries:
            subpath = os.path.relpath(entry.path, path)
            if source:
                source_file = os.path.join(source, subpath)
                try:
                    source_file_stat = os.stat(source_file)
                except FileNotFoundError:
                    source_file_stat = None
            if destination:
                destination_file = os.path.join(destination, subpath)
                try:
                    destination_file_stat = os.stat(destination_file)
                except FileNotFoundError:
                    destination_file_stat = None
            if incremental:
                if source and destination and config_file_stat and source_file_stat and destination_file_stat:
                    if not (source_file_stat.st_mtime > destination_file_stat.st_mtime or config_file_stat.st_mtime > destination_file_stat.st_mtime):
                        continue
            futures.append(executor.submit(func, config, source, destination, subpath, context))
        for future in concurrent.futures.as_completed(futures):
            result.append(future.result())
    return result

# WORKER TASKS

def texdiag_info_task(config, source, destination, subpath, context):
    result = {}
    result['info_key'] = subpath
    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    texdiag_command = config.get('TEXDIAG', 'info_command').format(options = config.get('TEXDIAG', 'info_options'), **context).format(
        source = source, sourcepath = sourcepath, sourcedir = sourcedir, subpath = subpath, **context
    )
    process = subprocess.Popen(texdiag_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
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

def texconv_task(config, source, destination, subpath, context):
    debug = bool(config.get('DEFAULT', 'debug'))
    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    destinationpath = os.path.join(destination, subpath); destinationdir = os.path.dirname(destinationpath)
    os.makedirs(destinationdir, exist_ok = True)
    texconv_command = config.get('TEXCONV', 'command').format(options = config.get('TEXCONV', 'options'), **context).format(
        sourcepath = sourcepath, sourcedir = sourcedir, destinationpath = destinationpath, destinationdir = destinationdir,
        source = source, destination = destination, subpath = subpath, subdir = os.path.dirname(subpath), **context, **context['info'][subpath]
    )
    process = subprocess.Popen(texconv_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
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

def convert_task(config, source, destination, subpath, context):
    debug = bool(config.get('DEFAULT', 'debug'))
    sourcepath = os.path.join(source, subpath); sourcedir = os.path.dirname(sourcepath)
    destinationpath = os.path.join(destination, subpath); destinationdir = os.path.dirname(destinationpath)
    os.makedirs(os.path.dirname(os.path.join(destination, subpath)), exist_ok = True)
    convert_command =  config.get('CONVERT', 'command').format(options = config.get('CONVERT', 'options'), **context).format(
        sourcepath = sourcepath, sourcedir = sourcedir, destinationpath = destinationpath, destinationdir = destinationdir,
        source = source, destination = destination, subpath = subpath, subdir = os.path.dirname(subpath), **context, **context['info'][subpath]
    )
    process = subprocess.Popen(convert_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
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

paths = sys.argv[1:]
config = configparser.ConfigParser({})
scriptdir = os.path.dirname(os.path.realpath(__file__))
config_file = os.path.join(scriptdir, '{}.cfg'.format(os.path.splitext(os.path.basename(__file__))[0]))

if os.path.exists(config_file):
    config.read(config_file)

for path in paths:
    entries = [x for x in scantree(path) if x.is_file()]
    texdiag_info_results = tasks_execute(config, "TEXDIAG", entries, texdiag_info_task, {'scriptdir': scriptdir, 'path': path})
    info = {x['info_key']: x for x in texdiag_info_results}
    tasks_execute(config, "CONVERT", entries, convert_task, {'scriptdir': scriptdir, 'path': path, 'info': info})
    ratio = float(config.get('TEXCONV', 'ratio'))
    def info_ratio_recalc(info, ratio):
        info['width'] = int(float(info['width']) * ratio)
        info['height'] = int(float(info['height']) * ratio)
        info['mipmaps'] = math.ceil(math.log(min(info['width'], info['height']), 2)) + 1
        return info
    info = dict(map(lambda x: (x[0], info_ratio_recalc(x[1], ratio)), info.items()))
    tasks_execute(config, "TEXCONV", entries, texconv_task, {'scriptdir': scriptdir, 'path': path, 'info': info})