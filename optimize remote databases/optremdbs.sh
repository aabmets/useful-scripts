#!/bin/bash
# ================================================================================== #
#                                                                                    #
#   MIT License                                                                      #
#                                                                                    #
#   Copyright (c) 2022 Mattias Aabmets                                               #
#                                                                                    #
#   Permission is hereby granted, free of charge, to any person obtaining a copy     #
#   of this software and associated documentation files (the "Software"), to deal    #
#   in the Software without restriction, including without limitation the rights     #
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell        #
#   copies of the Software, and to permit persons to whom the Software is            #
#   furnished to do so, subject to the following conditions:                         #
#                                                                                    #
#   The above copyright notice and this permission notice shall be included in all   #
#   copies or substantial portions of the Software.                                  #
#                                                                                    #
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR       #
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,         #
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE      #
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER           #
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,    #
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE    #
#   SOFTWARE.                                                                        #
#                                                                                    #
# ================================================================================== #
SCRIPT_VERSION="1.0.0"
DEPENDENCIES=("putty" "putty-tools" "parallel")

hosts_file="hosts.ini"
python_file="optremdbs.py"
remote_path="/users/admin/scripts/"


# ================================================================================== #
echo_title()
{
  echo "--------------------------------"
  echo "OPTIMIZE REMOTE DATABASES SCRIPT"
}

# ---------------------------------------------------------------------------------  #
echo_help()
{
  echo_title
  echo
  echo "This script reads a list of remote database hosts from the"
  echo "adjacent 'hosts.ini' file and tries to transfer the adjacent"
  echo "python script named 'optremdbs.py' to each remote host and"
  echo "execute it with the args passed to this script. Remote hosts"
  echo "can be either Windows or Linux machines. Linux hosts require"
  echo "the 'python-is-python3' package."
  echo
  echo "Syntax: optimize_dbs.sh [-n|V|D|h] [db_like_1 ...]"
  echo
  echo "positional params 'db_like_*':"
  echo "      Variable quantity of database names which to optimize."
  echo "      The database names can be in MySQL LIKE regex format."
  echo
  echo "options:"
  echo "-h     Print this help and exit."
  echo "-V     Print software version and exit."
  echo "-D     Print software dependencies and exit."
  echo "-n     Enables dry run mode, where the remote python scripts"
  echo "       will return the names of the databases to be optimized"
  echo "       without running any optimization on the databases."
  echo
}

# ---------------------------------------------------------------------------------  #
echo_deps()
{
  echo_title
  echo
  echo "Local Dependencies:"
  for dep in ${DEPENDENCIES[*]}; do
    echo "    $dep"
  done
  echo
}

# ---------------------------------------------------------------------------------  #
echo_version()
{
  echo_title
  echo
  echo "Version: $SCRIPT_VERSION"
  echo
}

# ---------------------------------------------------------------------------------  #
echo_usage()
{
  echo "Run this script with the '-h' option to display the usage guide."
  echo
}


# ================================================================================== #
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

# ---------------------------------------------------------------------------------  #
#  Ensure all local dependencies are installed before continuing.

for dep in ${LOCAL_DEPS[*]}; do
  if ! dpkg -s "$dep" &> /dev/null; then
    echo "ERROR! This script depends on the \"$dep\" package, which is missing!"
    echo && exit 1
  fi
done


# ================================================================================== #
# 'filter_hosts' function prints hostname if it is alive.

filter_hosts()
{
  host=${1//[$'\t\r\n']}
  if ping -c 1 -W 1 "$host" &> /dev/null; then
    echo "$host"
  fi
}
export -f filter_hosts

# ---------------------------------------------------------------------------------  #
#  This function sends over the python script file to the remote machine
#  and executes it with the args provided to this script.

optremdbs()
{
  remote_cmd="python ${1}/${2} ${3} -x ${4}"
  pscp -l admin -pw admin "$PWD/${2}" "${4}":"${1}" &> /dev/null
  plink -ssh -no-antispoof -l admin -pw admin "${4}" "$remote_cmd"
}
export -f optremdbs

# ---------------------------------------------------------------------------------  #
echo "==================== OPTIMIZING DATABASES ===================="
test="                            DRY RUN                           "
for opt in "$@"; do
  [[ "$opt" == "-n" ]] && echo "$test"
done

echo
echo "Getting alive hosts..."
echo

hosts_alive=$(parallel --keep-order filter_hosts :::: "$PWD/$hosts_file")
while IFS='' read -r host; do
  host="${host//[$'\t\r\n']}"
  if ! [[ "$hosts_alive" == *"$host"* ]]; then
    echo "$host - Not Responding!"
  else
    echo "$host - ALIVE!"
  fi
done < "$hosts_file"

echo
echo "Running scripts on alive hosts..."
echo

start_time=$(date -u +"%s.%N")
parallel --linebuffer optremdbs ::: "$remote_path" ::: "$python_file" ::: "${*}" ::: "$hosts_alive"
end_time=$(date -u +"%s.%N")
diff=$(date -u -d "0 $end_time sec - $start_time sec" +"%M min : %S sec")

echo
echo "Remote scripts total runtime:"
echo "    $diff"
echo
echo "========================== FINISHED =========================="

exit 0
