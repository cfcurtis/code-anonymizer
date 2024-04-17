import sys, os
from pathlib import Path
import logging
import zipfile
import shutil

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

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


def copy_and_anon(src: str, dest: str) -> None:
    """
    Walk a directory and anonymize all java files in it, saving to destination.
    Jar files are unpacked and any source files are also anonymized, then repacked.
    Other file types (data files, .class files, word documents, etc) are not copied.
    """
    for root, dirs, files in os.walk(src):
        dest_root = Path(dest) / Path(root).relative_to(src)
        dest_root.mkdir(exist_ok=True)
        for dir in dirs:
            dest_dir = dest_root / dir
            dest_dir.mkdir(exist_ok=True)

        for file in files:
            if file.endswith(".java"):
                # anonymize the file and write to dest
                src_file = Path(root) / file
                dest_file = dest_root / file
                anonymize_file(src_file, dest_file)
            elif file.endswith(".jar") or file.endswith(".zip"):
                # unpack the jar/zip file and anonymize any java files
                jar_name = file.replace(".", "_")
                with zipfile.ZipFile(Path(root) / file, "r") as z:
                    z.extractall(TEMP_DIR / jar_name)
                copy_and_anon(TEMP_DIR / jar_name, dest_root / jar_name)
                # recursively delete temp unpacked files
                shutil.rmtree(TEMP_DIR / jar_name)
            else:
                # don't copy the file
                logger.info(f"Skipping {file}, not java source code")
    
    # clean up any empty directories
    for root, dirs, files in os.walk(dest, topdown=False):
        for dir in dirs:
            if not os.listdir(Path(root) / dir):
                os.rmdir(Path(root) / dir)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 anon.py <src> <dest>")
        print("       where <src> is the root of all assignments to anonymize,")
        print("       <dest> is the name of the directory to save the anonymized versions.")
        sys.exit(1)
    
    TEMP_DIR.mkdir(exist_ok=True)
    copy_and_anon(sys.argv[1], sys.argv[2])
    # clean up the temp directory, should be empty at this point
    TEMP_DIR.rmdir()