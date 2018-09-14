# Optimize Textures Script

## Description

I took the code from my not yet finished mo2 plugin and stripped all the QT code from it. It supports the following:

 * Everything is configurable by modifying the `optimize_textures.json` file
 * Processing images using ImageMagick, see the following for options: https://www.imagemagick.org/script/command-line-processing.php
 * Processing images using TexConv (modified to support alpha-to-coverage if needed)
 * Scaling by ratio using TexConv. See the ratio option in the `optimize_textures.json` file
 * Custom options according to matching pattern, supporting stacked options when multiple patterns match
 * Incremental update, only updating what has been modified
 * Multi-threading configurable per tool

It runs the tools in the following order: inpurt -> ImageMagick -> TexConv -> output

## Usage
Drag & drop a directory onto the `optimize_textures.bat` file. This will process the directory according to the settings inside the `optimize_textures.json` file.

## Requirements
 * Python 3.5 >=
