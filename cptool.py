import argparse
import sqlite3
import hashlib
import zipfile
import filecmp
import shutil
import time
import re
import os

ARCHIVE_NAME_REGEX = "[a-fA-F0-9]{40}"
BACKUP_FILE_LENGTH = 40

REPO = os.path.expanduser("~/.cptool")
TAGS = os.path.join(REPO, ".cptags")
BACKUP = ".cpbackup"
SYNC = ".cpsync"


class CpException(Exception):
    pass


def ensure_dir_exists(directory, message=None):
    if not os.path.isdir(directory):
        if message is None:
            message = "Directory '%s' does not exist." % directory
        raise CpException(message)


INSERT_TAG = "INSERT OR REPLACE INTO tags VALUES (?,?,?)"
GET_TAG = "SELECT dir,zip FROM tags WHERE tag=?"
CREATE_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS tags (
    tag TEXT PRIMARY KEY,
    dir TEXT,
    zip TEXT
)
"""


def set_tag(directory, archive_path, tag):
    assert tag and os.path.isdir(directory) and os.path.isfile(archive_path)
    with sqlite3.connect(TAGS) as db:
        cursor = db.cursor()
        cursor.execute(CREATE_TAGS_TABLE)
        cursor.execute(INSERT_TAG, (tag, directory, archive_path))
        db.commit()


def revert_by_tag(tag):
    assert tag
    with sqlite3.connect(TAGS) as db:
        cursor = db.cursor()
        cursor.execute(GET_TAG, (tag,))
        result = cursor.fetchone()
    if not result:
        raise CpException("Tag '%s' does not exist." % tag)
    directory, archive_path = result
    revert(directory, archive_path)


GET_DIR = "SELECT tag,zip FROM tags WHERE dir=?"


def show_tag_history(directory):
    with sqlite3.connect(TAGS) as db:
        cursor = db.cursor()
        cursor.execute(GET_DIR, (directory,))
        result = cursor.fetchall()
    if not result:
        raise CpException("Directory '%s' has no backup history." % directory)
    for item in result:
        tag, archive_path = item
        if os.path.isfile(archive_path):
            created = os.path.getctime(archive_path)
            print "TAG=%s, CREATED=%s" % (tag, time.ctime(created))


def backup(directory, tag=None):
    ensure_dir_exists(directory)
    if not os.path.isdir(REPO):
        os.makedirs(REPO)
    assert os.path.isdir(REPO)
    key = str(time.time())
    sha = hashlib.sha1(key).hexdigest()
    archive_path = os.path.join(REPO, sha)
    assert not os.path.isfile(archive_path)
    shutil.make_archive(archive_path, "zip", directory)
    backup_path = os.path.join(directory, BACKUP)
    with open(backup_path, 'w') as b:
        b.write(sha)
    assert os.path.getsize(backup_path) == BACKUP_FILE_LENGTH
    if tag:
        set_tag(directory, archive_path + ".zip", tag)


def get_archive_name(directory):
    assert os.path.isdir(directory)
    backup_path = os.path.join(directory, BACKUP)
    if not os.path.isfile(backup_path):
        raise CpException("Backup file missing in '%s'." % directory)
    with open(backup_path) as b:
        archive_name = b.readline()
    if not re.compile(ARCHIVE_NAME_REGEX).match(archive_name):
        raise CpException("Backup file in '%s' corrupted." % directory)
    return archive_name + ".zip"


def revert(directory, archive_path=None):
    ensure_dir_exists(directory)
    if archive_path is None:
        archive_name = get_archive_name(directory)
        archive_path = os.path.join(REPO, archive_name)
    if not os.path.isfile(archive_path):
        raise CpException("Archive '%s' missing." % archive_path)
    shutil.rmtree(directory)
    with zipfile.ZipFile(archive_path) as zf:
        zf.extractall(directory)


def find_diff(src, dst):
    if os.path.isdir(dst):
        diff = filecmp.dircmp(src, dst)
        diff_list = diff.left_only + diff.diff_files
    else:
        diff_list = [f for f in os.listdir(src)]
    ignore = (BACKUP, SYNC)
    return filter(lambda l: l not in ignore, diff_list)


def apply_diff(src, dst, diff_list=None, auto_backup=True, backup_tag=None):
    if diff_list is None:
        diff_list = find_diff(src, dst)
    if diff_list:
        if auto_backup:
            backup(dst, backup_tag)
        for item in diff_list:
            src_item = os.path.join(src, item)
            dst_item = os.path.join(dst, item)
            if os.path.isdir(src_item):
                shutil.copytree(src_item, dst_item)
            else:
                shutil.copy(src_item, dst_item)


def generate_sync_file(directory, sources):
    ensure_dir_exists(directory)
    absolute_paths = [os.path.abspath(s) for s in sources]
    sync_file = os.path.join(directory, SYNC)
    with open(sync_file, "w") as cp:
        cp.writelines(absolute_paths)
    assert os.path.getsize(sync_file) > 0


def sync(directory, backup_tag=None):
    ensure_dir_exists(directory)
    sync_path = os.path.join(directory, SYNC)
    if not os.path.isfile(sync_path):
        raise CpException("Sync file for '%s' missing." % directory)
    with open(sync_path) as s:
        src_list = s.read().splitlines()
    if not src_list:
        raise CpException("Sync file is empty.")
    for src in src_list:
        ensure_dir_exists(src, "Invalid source dir: '%s'." % src)
    backup(directory, backup_tag)
    for src in src_list:
        apply_diff(src, directory, auto_backup=False, backup_tag=backup_tag)


class ValidDirAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        directories = values if isinstance(values, list) else [values]
        for d in directories:
            if not (os.path.isdir(d) and os.access(d, os.W_OK)):
                raise argparse.ArgumentError(self, "Invalid dir: %s" % d)
        setattr(namespace, self.dest, values)


def diff_parser():
    parser = argparse.ArgumentParser(
        description="Compare and copy missing files from one dir to another"
    )

    subparsers = parser.add_subparsers(title="Options", dest="opt")
    tag_parser = argparse.ArgumentParser(add_help=False)
    tag_parser.add_argument("-t", "--tag", help="Backup tag")

    cp = subparsers.add_parser("cp", help="Copy from one dir to another",
                               parents=[tag_parser])
    cp.add_argument("src", help="source dir", action=ValidDirAction)
    cp.add_argument("dst", help="destination dir", action=ValidDirAction)

    rv = subparsers.add_parser("rv", help="Revert")
    rv.add_argument("-d", "--dir", help="dir to revert", action=ValidDirAction)
    rv.add_argument("-t", "--tag", help="tag to revert")

    sync = subparsers.add_parser("sync", help="Auto-sync", parents=[tag_parser])
    sync.add_argument("dir", help="dir to sync", action=ValidDirAction)

    mksync = subparsers.add_parser("mksync", help="Generate auto-sync folder")
    mksync.add_argument("dir", help="dir to auto-sync", action=ValidDirAction)
    mksync.add_argument("src", nargs='+', help="source dirs",
                        action=ValidDirAction)

    history = subparsers.add_parser("th", help="Tag history")
    history.add_argument("dir", help="dir to check", action=ValidDirAction)

    return parser


def invoke_revert(directory=None, tag=None):
    if not (directory or tag):
        raise CpException("rv: either directory or tag has to be provided.")
    if directory:
        revert(directory)
    else:
        revert_by_tag(tag)


if __name__ == '__main__':
    args = diff_parser().parse_args()
    opts = {
        "cp": lambda: apply_diff(args.src, args.dst, backup_tag=args.tag),
        "rv": lambda: invoke_revert(args.dir, args.tag),
        "th": lambda: show_tag_history(args.dir),
        "sync": lambda: sync(args.dir, args.tag),
        "mksync": lambda: generate_sync_file(args.dir, args.src),
    }
    try:
        opts[args.opt]()
    except CpException as e:
        print str(e)
