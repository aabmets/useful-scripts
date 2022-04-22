#!/bin/bash


# -------------------------------------------------------------------------------- #
#  Define settings.

hosts_file="hosts.ini"
remote_file="optimize_dbs.py"
remote_path="/users/admin/scripts/"


# -------------------------------------------------------------------------------- #
#  Define constants.

SCRIPT_VERSION="1.0.0"
LOCAL_DEPS=("putty" "putty-tools")
REMOTE_DEPS=("python3" "python-is-python3")


# ================================================================================ #
echo_title()
{
  echo "--------------------------------"
  echo "OPTIMIZE REMOTE DATABASES SCRIPT"
}

# -------------------------------------------------------------------------------- #
echo_help()
{
  echo_title
  echo
  echo "This script reads the list of remote database hosts from the"
  echo "adjacent 'hosts.ini' file and tries to transfer the adjacent"
  echo "python script named 'optimize_dbs.py' to each remote host and"
  echo "execute it with the args passed to this script."
  echo
  echo "Syntax: optimize_dbs.sh [-n|h|V] [db_like_1 ...]"
  echo
  echo "positional params 'db_like_*':"
  echo "      Variable quantity of database names which to optimize."
  echo "      The database names can be in MySQL LIKE regex format."
  echo
  echo "options:"
  echo "h     Print this help and exit."
  echo "V     Print software version and exit."
  echo "D     Print software dependencies and exit."
  echo "n     Enables dry run mode, where the remote python scripts"
  echo "      will return the names of the databases to be optimized"
  echo "      without running any optimization on the databases."
  echo
}

# -------------------------------------------------------------------------------- #
echo_deps()
{
  echo_title
  echo
  echo "Local dependencies:"
  for dep in ${LOCAL_DEPS[*]}; do
    echo "    $dep"
  done
  echo
  echo "Remote dependencies:"
    for dep in ${REMOTE_DEPS[*]}; do
    echo "    $dep"
  done
  echo
}

# -------------------------------------------------------------------------------- #
echo_version()
{
  echo_title
  echo
  echo "Version: $SCRIPT_VERSION"
  echo
}

# -------------------------------------------------------------------------------- #
echo_usage()
{
  echo "Run this script with the '-h' option to display the usage guide."
  echo
}


# ================================================================================  #
#  Parse and evaluate the args.

if [[ "$*" == "" ]]; then
  echo "ERROR! This script cannot be executed without any arguments!"
  echo_usage && exit 1
fi

while getopts ":nDVh" option; do
  case ${option} in
    n)
      if [[ $# -eq 1 ]]; then
        echo "ERROR! This script cannot be executed in dry run mode without database names!"
        echo_usage && exit 1
      fi ;;
    D)
      echo_deps && exit 0 ;;
    V)
      echo_version && exit 0 ;;
    h)
      echo_help && exit 0 ;;
    *)
      echo "ERROR! This script does not accept the option '-$OPTARG'."
      echo_usage && exit 1 ;;
  esac
done

# --------------------------------------------------------------------------------  #
#  Ensure all local dependencies are installed before continuing.

for dep in ${LOCAL_DEPS[*]}; do
  if ! dpkg -s "$dep" &> /dev/null; then
    echo "ERROR! This script depends on the \"$dep\" package, which is missing!"
    echo && exit 1
  fi
done


# ================================================================================  #
#  The main worker function sanitizes the hostname and checks
#  if the remote host is alive. If it is, then it sends over
#  the python script file to the remote machine and executes
#  it with the args provided to this script.

optimize_dbs()
{
  host=${4//[$'\t\r\n']}
  remote_cmd="python ${1}/${2} ${3}"
  if ! ping -c 1 -W 1 "$host" &> /dev/null; then
    echo "ERROR! Remote host \"$host\" is not responding!"
  else
    pscp -l admin -pw admin "$PWD/${2}" "$host":"${1}" &> /dev/null
    plink -no-antispoof -l admin -pw admin "$host" "$remote_cmd"
  fi
}
export -f optimize_dbs

# --------------------------------------------------------------------------------  #
echo "==================== OPTIMIZING DATABASES ===================="
test="                            DRY RUN                           "
for opt in "$@"; do
  [[ "$opt" == "-n" ]] && echo "$test"
done
echo

start_time=$(date -u +"%s.%N")
parallel optimize_dbs {} ::: "$remote_path" ::: "$remote_file" ::: "${*}" :::: "$PWD/$hosts_file"
end_time=$(date -u +"%s.%N")

diff=$(date -u -d "0 $end_time sec - $start_time sec" +"%M:%S:%N")
IFS=':' read -r -a array <<< "$diff"

echo
echo "Total time taken by remote hosts:"
echo "    ${array[0]} minutes"
echo "    ${array[1]} seconds"
echo "    ${array[2]:0:2} milliseconds"
echo
echo "========================== FINISHED =========================="

exit 0
