#!/usr/bin/env python

from sys import exit, stderr
from os import getcwd, path
from subprocess import check_output
from argparse import ArgumentParser, RawTextHelpFormatter
from util_funcs import get_html, HTMLGetError
from mirrors import Mirrors
from bs4 import BeautifulSoup

parser = ArgumentParser(
    description=(
        "Find the fastest Ubuntu apt mirrors.\n"
        "Generate new sources.list file."
    ),
    formatter_class=RawTextHelpFormatter
)
parser.add_argument(
    '-t',
    '--top-number',
    nargs=1,
    type=int,
    help=(
        "specify number of mirrors to return\n"
        "default: 1\n"
    ),
    default=1,
    metavar='NUMBER'
)

STATUS_ARGS = (
    "up-to-date",
    "one-day-behind",
    "two-days-behind",
    "one-week-behind",
    "unknown"
)

test_group = parser.add_mutually_exclusive_group(required=False)
test_group.add_argument(
    '-m',
    '--min-status',
    nargs=1,
    choices=STATUS_ARGS,
    help=(
        "return mirrors with minimum status\n"
        "choices:\n"
        "   %(up)s\n"
        "   %(day)s\n"
        "   %(two_day)s\n"
        "   %(week)s\n"
        "   %(unknown)s\n"
        "default: %(up)s\n" % {
            'up': STATUS_ARGS[0],
            'day': STATUS_ARGS[1],
            'two_day': STATUS_ARGS[2],
            'week': STATUS_ARGS[3],
            'unknown': STATUS_ARGS[4]
        }
    ),
    default=STATUS_ARGS[0],
    metavar='STATUS'
)
test_group.add_argument(
    '-p',
    '--ping-only',
    action='store_true',
    help=(
        "rank mirror(s) by latency only, disregard status(es)\n"
        "cannot be used in conjunction with -m/--min-status\n"
    ),
    default=False
)

output_group = parser.add_mutually_exclusive_group(required=False)
output_group.add_argument(
    '-c',
    '--choose',
    action='store_true',
    help=(
        "choose mirror from a list\n"
        "requires -t/--top-num NUMBER where NUMBER > 1\n"
    ),
    default=False
)
output_group.add_argument(
    '-l',
    '--list',
    dest='list_only',
    action='store_true',
    help=(
        "print list of mirrors only, don't generate file\n"
        "cannot be used in conjunction with -c/--choose\n"
    ),
    default=False
)

args = parser.parse_args()


# argparse returns list type for only choice arguments, not default
def index_zero(flag):
    """Get first element of list or return unchanged"""
    if type(flag) is list:
        return flag[0]

    return flag

flag_number = index_zero(args.top_number)
flag_status = index_zero(args.min_status).replace('-', ' ')
if flag_status != 'unknown':
    flag_status = flag_status[0].upper() + flag_status[1:]

flag_list = args.list_only
flag_choose = args.choose
flag_ping = args.ping_only

if flag_choose and (not flag_number or flag_number < 2):
    parser.print_usage()
    exit((
        "error: -c/--choose option requires -t/--top-number NUMBER "
        "where NUMBER is greater than 1."
    ))


def not_ubuntu():
    """Notify of incompatibility"""
    exit("Not an Ubuntu OS")

try:
    release = check_output(["lsb_release", "-ics"])
except OSError:
    not_ubuntu()
else:
    release = [s.strip() for s in release.decode('utf-8').split()]

if release[0] == 'Debian':
    exit("Debian is not currently supported")
elif release[0] != 'Ubuntu':
    not_ubuntu()

directory = '/etc/apt/'
apt_file = 'sources.list'
sources_path = directory + apt_file
if not path.isfile(sources_path):
    exit("%s must exist as file" % sources_path)

codename = release[1][0].upper() + release[1][1:]
ubuntu_url = "mirrors.ubuntu.com"
mirror_list = "http://%s/mirrors.txt" % ubuntu_url

stderr.write("Getting list of mirrors...")
try:
    archives = Mirrors(get_html(mirror_list).splitlines())
except HTMLGetError as err:
    exit("Error getting list from %s:\n\t%s" % (mirror_list, err))

stderr.write("done.\n")
archives.get_rtts()
if archives.got["ping"] < flag_number:
    flag_number = archives.got["ping"]

if flag_number == 0:
    exit((
        "Cannot connect to any mirrors in %s\n."
        "Minimum latency of this machine may exceed"
        "2.5 seconds or\nthere may be other unknown"
        "TCP connectivity issues.\n" % mirror_list
    ))

abort_launch = False
if not flag_ping:
    launchpad_base = "https://launchpad.net"
    launchpad_url = launchpad_base + "/ubuntu/+archivemirrors"
    stderr.write("Getting list of launchpad URLs...")
    try:
        launchpad_html = get_html(launchpad_url)
    except HTMLGetError as err:
        stderr.write((
            "Unable to retrieve list of launchpad sites\n"
            "Reverting to latency only"
        ))
        abort_launch = True
    else:
        stderr.write("done.\n")
        prev = ""
        for element in BeautifulSoup(launchpad_html).table.descendants:
            try:
                url = element.a
            except AttributeError:
                pass
            else:
                try:
                    url = url["href"]
                except TypeError:
                    pass
                else:

                    if url in archives.urls:
                        archives.urls[url]["Launchpad"] = launchpad_base + prev

                    if url.startswith("/ubuntu/+mirror/"):
                        prev = url

        hardware = check_output(["uname", "-m"]).strip().decode('utf-8')
        if hardware == 'x86_64':
            hardware = 'amd64'
        else:
            hardware = 'i386'

        stderr.write("Looking up %d status(es)\n" % flag_number)
        archives.lookup_statuses(
            flag_number, flag_status, codename, hardware
        )

if (flag_number > 1) and not flag_ping:
    stderr.write('\n')

repo_name = ""
found = False
skip_gen_msg = "Skipping file generation."
with open(sources_path, 'r') as f:
    lines = f.readlines()

    def confirm_mirror(uri):
        """Check if line follows correct sources.list URI"""
        deb = ('deb', 'deb-src')
        proto = ('http://', 'ftp://')
        if (uri and (uri[0] in deb) and
                (proto[0] in uri[1] or
                 proto[1] in uri[1])):
            return True

        return False

    repo = []
    required_repo = "main"
    for line in lines:
        fields = line.split()
        if confirm_mirror(fields):
            if (not found and
                    (release[1] in fields[2]) and
                    (fields[3] == required_repo)):
                repo += [fields[1]]
                found = True
                continue
            elif fields[2] == '%s-security' % (release[1]):
                repo += [fields[1]]
                break

    if not repo:
        stderr.write((
            "Error finding current %s repository in %s\n%s\n" %
            (required_repo, sources_path, skip_gen_msg)
        ))
    else:
        repo_name = repo[0]


def assign_defaults(info, keys, default):
    for key in keys:
        if key not in info:
            info[key] = default

rank = 0
final = []
current_key = -1
for i in range(flag_number):
    url = archives.ranked[i]
    info = archives.urls[url]
    host = info["Host"]
    if url == repo_name:
        host += " (current)"
        current_key = rank

    if not flag_ping and not abort_launch:
        if "Status" in info:
            assign_defaults(info, ("Org", "Speed"), "N/A")
            print((
                "%(rank)d. %(mirror)s\n%(tab)sLatency: %(ms)d ms\n"
                "%(tab)sOrg:     %(org)s\n%(tab)sStatus:  %(status)s\n"
                "%(tab)sSpeed:   %(speed)s" % {
                    'tab': '    ',
                    'rank': rank + 1,
                    'mirror': host,
                    'ms': info["Latency"],
                    'org': info["Organisation"],
                    'status': info["Status"],
                    'speed': info["Speed"]
                }
            ))
        else:
            continue
    else:
        print("%d. %s: %d ms" % (rank+1, info["Host"], info["Latency"]))

    rank += 1
    final.append(url)
    if rank == flag_number:
        break

try:
    input = raw_input
except NameError:
    pass


def ask(query):
    global input
    answer = input(query)
    return answer


key = 0
if flag_choose:
    query = "Choose a mirror (1 - %d)\n'q' to quit " % len(final)
    key = ask(query)
    while True:
        try:
            key = int(key)
        except ValueError:
            if key == 'q':
                exit()

        if (type(key) is str) or ((key < 1) or (key > rank)):
            query = "Invalid entry "
            key = ask(query)
            continue

        break

    key = key - 1

if flag_list:
    exit()

# Writing a new file using the currently used mirror would be needless work
if current_key == key:
    exit((
        "%s is the currently used mirror.\n%s" %
        (archives.urls[repo_name]["Host"], skip_gen_msg)
    ))

mirror = final[key]
lines = ''.join(lines)
for r in repo:
    lines = lines.replace(r, mirror)


def yes_or_no(query):
    """Get definitive answer"""
    opts = ('yes', 'no')
    answer = ask(query)
    while answer != opts[0]:
        if answer == opts[1]:
            exit(0)
        answer = ask("Please enter '%s' or '%s': " % opts)


wd = getcwd()
if wd == directory[0:-1]:
    query = (
        "'%(dir)s' is the current directory.\n"
        "Generating a new '%(apt)s' file will "
        "overwrite the current file.\n"
        "You should copy or backup '%(apt)s' before replacing it.\n"
        "Continue?\n[yes|no] " % {
            'dir': directory,
            'apt': apt_file
        }
    )
    yes_or_no(query)

write_file = wd + "/" + apt_file
try:
    with open(write_file, 'w') as f:
        f.write(lines)
except IOError as err:
    if err.strerror == 'Permission denied':
        exit((
            "%s\nYou do not own %s\n"
            "Please run the script from a directory you own." % (err, wd)
        ))
    else:
        exit(err)
else:
    print("New config file saved to %s" % write_file)

exit()
