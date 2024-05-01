import sys, os
from pathlib import Path
import logging
import zipfile
import shutil
import datetime
import filecmp
import argparse

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Global constants and singletons
TEMP_DIR = Path("temp")
ENTITIES = ["EMAIL_ADDRESS", "PERSON", "STUDENT_ID"]
OPERATORS = {
    "PERSON": OperatorConfig("replace", {"new_value": "<NAME>"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "anon@mtroyal.ca"}),
    "STUDENT_ID": OperatorConfig("replace", {"new_value": "00000000"}),
}

# not exactly constants, but defined at argparse time
exclude = [
    "lib",
    "bin",
    "build",
    "dist",
    "junit",
    "hamcrest",
    "checkstyle",
    "gson",
    "_MACOSX",
    ".DS_Store",
    ".git",
    ".idea",
    ".vscode",
]

compare_sizes = False

# The analyzer and anonymizer engines are singletons, should be created once and reused
analyzer = AnalyzerEngine()

# define custom recognizer for student ID (9 digits)
id_pattern = Pattern(name="student_id_pattern", regex="\d{8,10}", score=0.5)
id_recognizer = PatternRecognizer(supported_entity="STUDENT_ID", patterns=[id_pattern])
analyzer.registry.add_recognizer(id_recognizer)
anonymizer = AnonymizerEngine()
logger = logging.getLogger(__name__)


def anonymize(text: str, entities: list = ENTITIES, operators: dict = OPERATORS) -> str:
    """Do the actual text anonymization"""
    try:
        results = analyzer.analyze(text=text, language="en", entities=entities)
        anonymized_text = anonymizer.anonymize(
            text=text, analyzer_results=results, operators=operators
        )
    except Exception as e:  # I'm not sure what kind of exception to expect here
        logger.error(f"Anonymization failed: {e}")
        raise e

    return anonymized_text.text


def anonymize_file(src: str, dest: str) -> bool:
    """
    Read a file from src, anonymize the contents, write to dest.
    Returns True if successful, False otherwise.
    """
    try:
        with open(src, "r") as f:
            text = f.read()
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return False

    success = True
    # go line by line and only anonymize comments
    multiline_comment = False
    anonymized_text = ""
    for line in text.split("\n"):
        if "/*" in line:
            multiline_comment = True
        if multiline_comment or line.strip().startswith("//"):
            try:
                line = anonymize(line)
            except Exception as e:
                # let it slide, but note that something failed
                success = False

        if "*/" in line:
            multiline_comment = False

        # either way, append the line
        anonymized_text += line + "\n"

    try:
        with open(dest, "w") as f:
            f.write(anonymized_text)
    except IOError as e:
        logger.error(f"Error writing file: {e}")
        return False

    return success


def already_exists(student_root: str, file_path: str) -> bool:
    """
    Check if a file already exists somewhere in the student's directory.
    Recursively search through the submission for the file.
    """
    file_path = Path(file_path)
    filename = file_path.name
    file_size = Path(file_path).stat().st_size
    for target_root, _, files in os.walk(student_root):
        if filename in files:
            if compare_sizes:
                target_size = (Path(target_root) / filename).stat().st_size
                return abs(target_size - file_size) < 10  # allow for small differences
            else:
                return True
                # just look at filename, assumes that students only have one actual file of each name

    return False


def process_archive(root: str, file: str, dest_root: str, student_root: str) -> int:
    """
    Unpack the jar/zip to a temp directory and anonymize any java files.
    Compares source code to any included source files in the parent directory,
    does not copy from jar if the files are the same.

    Returns the number of files anonymized without error.
    """

    jar_name = file.replace(".", "_")
    try:
        with zipfile.ZipFile(root / file, "r") as z:
            z.extractall(TEMP_DIR / jar_name)
    except zipfile.BadZipFile as e:
        logger.warning(f"Could not unzip {root / file}, skipping: {e}")
        return 0

    # anonymize the files in the jar, if they aren't already in the student's directory
    n_processed = copy_and_anon(TEMP_DIR / jar_name, dest_root / jar_name, student_root)

    # recursively delete temp unpacked files
    shutil.rmtree(TEMP_DIR / jar_name)
    return n_processed


def copy_and_anon(src: str, dest: str, student_root: str = None) -> int:
    """
    Walk a directory and anonymize all java files in it, saving to destination.
    Jar files are unpacked and any source files are also anonymized, then repacked.
    Other file types (data files, .class files, word documents, etc) are not copied.

    Returns the number of files anonymized without error.
    """
    n_processed = 0
    in_zip = str(TEMP_DIR) in str(src)
    for root, dirs, files in os.walk(src):
        root = Path(root)

        # create the same directory structure in dest, skipping over
        # anything that isn't likely to contain student code (lib, bin, etc)
        dest_root = Path(dest) / root.relative_to(src)
        dest_root.mkdir(exist_ok=True)
        for dir in dirs:
            ldir = dir.lower()
            if exclude and any([x in ldir for x in exclude]):
                dirs.remove(dir)
                continue
            dest_dir = dest_root / dir
            dest_dir.mkdir(exist_ok=True)

        # go through the files and look for java or archives
        for file in files:
            # skip over excluded files
            lfile = file.lower()
            if exclude and any([x in lfile for x in exclude]):
                continue

            if student_root and not in_zip and student_root not in str(dest_root):
                # we've moved out of the student's directory, reset to None
                student_root = None

            # The first time we find a java or jar file, assume it's the root of that
            # student or group's directory
            if not student_root and (file.endswith(".java") or file.endswith(".jar")):
                student_root = str(dest_root)

            if file.endswith(".java"):
                if already_exists(student_root, root / file):
                    logger.info(f"Skipping {root / file}, already exists")
                    continue

                # anonymize the file and write to dest
                src_file = root / file
                dest_file = dest_root / file
                if anonymize_file(src_file, dest_file):
                    n_processed += 1

            elif file.endswith(".jar") or file.endswith(".zip"):
                n_processed += process_archive(root, file, dest_root, student_root)
            else:
                # don't copy the file
                logger.info(f"Skipping {root / file}, not java source code")

    # clean up any empty directories
    for root, dirs, files in os.walk(dest, topdown=False):
        for dir in dirs:
            if not os.listdir(Path(root) / dir):
                os.rmdir(Path(root) / dir)

    return n_processed


def main() -> None:
    """
    Create the temp directory, set up logging, then start chewing through files.
    """
    global compare_sizes, exclude

    parser = argparse.ArgumentParser(
        description="Anonymize comments in student coding assignments (in Java)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("src", help="The root of all assignments to anonymize")
    parser.add_argument(
        "dest", help="The name of the directory to save the anonymized versions"
    )
    parser.add_argument(
        "-x",
        "--exclude",
        help="A comma-separated list of directory or jar filenames to exclude (case-insensitive, partial match)",
        default=",".join(exclude),
    )
    parser.add_argument(
        "-a",
        "--append",
        help="Append excluded filenames instead of replacing",
        action="store_true",
    )
    parser.add_argument(
        "-s",
        "--compare-sizes",
        help="Compare file sizes to determine if a file is already anonymized",
        action="store_true",
        default=compare_sizes,
    )

    args = parser.parse_args()

    # update the global args
    if args.append:
        exclude += args.exclude.lower().split(",")
    else:
        exclude = args.exclude.lower().split(",")

    compare_sizes = args.compare_sizes

    TEMP_DIR.mkdir(exist_ok=True)
    dest_dir = Path(args.dest)
    dest_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        filename=dest_dir / "codeanon.log",
        encoding="utf-8",
        level=logging.INFO,
    )
    logger.info(f"Anonymizing {args.src} to {args.dest}")
    logger.info(f"Start time: {datetime.datetime.now()}")
    print("Anonymizing code, this may take a while...")

    n_anon = copy_and_anon(args.src, dest_dir)

    logger.info(f"End time: {datetime.datetime.now()}")
    print(f"{n_anon} anonymized files written to {args.dest}")

    # clean up the temp directory, should be empty at this point
    TEMP_DIR.rmdir()


if __name__ == "__main__":
    main()
