import sys, os
from pathlib import Path
import logging
import zipfile
import shutil
import datetime
import filecmp

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Directories and files that are unlikely to contain student code
SKIP_DIRS = ["lib", "bin", "build", "dist"]
SKIP_JARS = ["junit", "hamcrest", "checkstyle", "gson"]

TEMP_DIR = Path("temp")
ENTITIES = ["EMAIL_ADDRESS", "PERSON", "STUDENT_ID"]
OPERATORS = {
    "PERSON": OperatorConfig("replace", {"new_value": "<NAME>"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "anon@mtroyal.ca"}),
    "STUDENT_ID": OperatorConfig("replace", {"new_value": "00000000"}),
}

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
    except Exception as e:
        logger.error(f"Anonymization failed: {e}")
        return text
    return anonymized_text.text


def anonymize_file(src: str, dest: str) -> None:
    """Read a file from src, anonymize the contents, write to dest"""
    try:
        with open(src, "r") as f:
            text = f.read()
    except IOError as e:
        logger.error(f"Error reading file: {e}")
        return

    # go line by line and only anonymize comments
    multiline_comment = False
    anonymized_text = ""
    for line in text.split("\n"):
        if "/*" in line:
            multiline_comment = True
        if multiline_comment or line.strip().startswith("//"):
            line = anonymize(line)
        if "*/" in line:
            multiline_comment = False

        # either way, append the line
        anonymized_text += line + "\n"

    try:
        with open(dest, "w") as f:
            f.write(anonymized_text)
    except IOError as e:
        logger.error(f"Error writing file: {e}")
        return


def process_archive(root: str, file: str, dest_root: str) -> None:
    """
    Unpack the jar/zip to a temp directory and anonymize any java files.
    Compares source code to any included source files in the parent directory,
    does not copy from jar if the files are the same.
    """

    # skip over any non-student jars
    if any(skip in file.lower() for skip in SKIP_JARS):
        return

    jar_name = file.replace(".", "_")
    with zipfile.ZipFile(root / file, "r") as z:
        z.extractall(TEMP_DIR / jar_name)

    # go through the unpacked files and delete any that already exist
    for temp_root, _, files in os.walk(TEMP_DIR / jar_name):
        temp_root = Path(temp_root)
        for file in files:
            if not file.endswith(".java"):
                continue
            jarred_file = temp_root / file
            uncorked_file = root / file

            if uncorked_file.exists() and filecmp.cmp(
                jarred_file, uncorked_file, shallow=False
            ):
                # the files are the same, delete the temp file
                os.remove(jarred_file)

    # finally, anonymize any remaining java files from the jar
    copy_and_anon(TEMP_DIR / jar_name, dest_root / jar_name)
    # recursively delete temp unpacked files
    shutil.rmtree(TEMP_DIR / jar_name)


def copy_and_anon(src: str, dest: str) -> None:
    """
    Walk a directory and anonymize all java files in it, saving to destination.
    Jar files are unpacked and any source files are also anonymized, then repacked.
    Other file types (data files, .class files, word documents, etc) are not copied.
    """
    for root, dirs, files in os.walk(src):
        root = Path(root)

        # create the same directory structure in dest, skipping over
        # anything that isn't likely to contain student code (lib, bin, etc)
        dest_root = Path(dest) / root.relative_to(src)
        dest_root.mkdir(exist_ok=True)
        for dir in dirs:
            if dir.lower() in SKIP_DIRS:
                dirs.remove(dir)
                continue
            dest_dir = dest_root / dir
            dest_dir.mkdir(exist_ok=True)

        # go through the files and look for java or archives
        for file in files:
            if file.endswith(".java"):
                # anonymize the file and write to dest
                src_file = root / file
                dest_file = dest_root / file
                anonymize_file(src_file, dest_file)
            elif file.endswith(".jar") or file.endswith(".zip"):
                process_archive(root, file, dest_root)
            else:
                # don't copy the file
                logger.info(f"Skipping {root / file}, not java source code")

    # clean up any empty directories
    for root, dirs, files in os.walk(dest, topdown=False):
        for dir in dirs:
            if not os.listdir(Path(root) / dir):
                os.rmdir(Path(root) / dir)


def main() -> None:
    """
    Create the temp directory, set up logging, then start chewing through files.
    """
    
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <src> <dest>")
        print("       where <src> is the root of all assignments to anonymize,")
        print(
            "       <dest> is the name of the directory to save the anonymized versions."
        )
        sys.exit(1)

    TEMP_DIR.mkdir(exist_ok=True)
    dest_dir = Path(sys.argv[2])
    dest_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        filename=dest_dir / "codeanon.log",
        encoding="utf-8",
        level=logging.INFO,
    )
    logger.info(f"Anonymizing {sys.argv[1]} to {sys.argv[2]}")
    logger.info(f"Start time: {datetime.datetime.now()}")
    copy_and_anon(sys.argv[1], dest_dir)
    logger.info(f"End time: {datetime.datetime.now()}")

    # clean up the temp directory, should be empty at this point
    TEMP_DIR.rmdir()


if __name__ == "__main__":
    main()