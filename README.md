# Code Anonymization Script
This repo contains a Python script to anonymize student code submissions. At the moment, it is hard-coded to process java files, and it only anonymizes information in comments (the most likely place for student identifying information).

## Overview
Student submissions can be in any directory structure, including zip files. The script does the following:
- Creates a destination directory
- Recursively copies the directory structure of the source directory to the destination directory
- Walks the source to find java files, anonymizing any comments, then writes the anonymized file to the corresponding destination
- If a zip or jar file is encountered, it is extracted to a temp directory, processed, then copied over to the destination without re-packing. Any non-java files are ignored.
- To try to avoid duplicate files, java files inside jars are compared to files in the parent directory, and if they match then the jar file is ignored.

## Installation and Usage
Note: this project depends on [Microsoft Presidio](https://microsoft.github.io/), which uses spaCy to detect identifying information such as names and student ids. This script will download the spaCy model `en_core_web_lg` the first time it is run, which is about 560MB.

### Using Pip
1. Clone and install with git + pip:
    ```bash
    pip install git+https://github.com/cfcurtis/code-anonymizer.git
    ```
2. Run the script with the following command:
   ```bash
   code-anonymizer <src> <dest>
   ```
   where `<src>` is the path to the root directory containing assignments, and `<dest>` is the name of a new directory to create containing the anonymized versions.

### From source
1. Clone this repo
2. Install the dependencies:
   ```bash
   pip install presidio-analyzer
   pip install presidio-anonymizer
   ```
3. Run the script with the following command:
   ```bash
   python anon.py <src> <dest>
   ```
   where `<src>` is the path to the root directory containing assignments, and `<dest>` is the name of a new directory to create containing the anonymized versions.

## Excluding Files
To exclude directories or filenames from being processed (e.g. non-student files), pass the argument `--exclude` or `-x` followed by a comma-separated list of directories or files. The default value is:

```bash
lib,bin,build,dist,junit,hamcrest,checkstyle,gson,_MACOSX,.DS_Store
```

By default, this list will be **replaced** by any `-x` arguments. To append to the list, use the `--append` or `-a` flag.