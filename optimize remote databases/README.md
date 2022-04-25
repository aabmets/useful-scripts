# Optimize Remote Databases


### Description

This script optimizes databases on remote database servers and is fully functional.
This script was created for a potential employer as part of a job application. 

The 'optremdbs.sh' shell script connects to each remote host over SSH, uploads the adjacent 
'remote_script.py' file to each host and executes it with the args provided to the shell script in the command line. 
Due to the nature of the implementation of this solution, it is trivial to modify the script files to run arbitrary Python scripts on remote machines.

### Exercise Premise

* Create a tool to optimize database tables over multiple database servers in the network. 
* The tool must consist of two script files, where one has to be a shell script and the other written in Python.
* The first script is called from the command line from the central management server, which in turn
invokes the second script over SSH on each database server in the network.
* The applicant is free to choose which script is written in which language.
* The list of server host names must be read from a config file, the format of which can be freely chosen by the applicant.
* The first script must accept a list of database names or regex words and the option '-n' for dry run as parameters.
* The first script must forward any command line args to the second script.
* The second script has full privileged access to the local database server.
* The second script should try to optimize as many tables of as many matching databases as possible.
* The second script must not run 'OPTIMIZE TABLE' mysql command, when the 'dry run' option is provided.
* The first script must print out:
  * How many tables each host succeeded / failed to optimize.
  * how long it took for each remote host.
  * How long it took for all hosts in total.
  * Any host or database connectivity error messages.
* The applicant should comment or document the scripts as they deem necessary.
* The applicant is free to use any shell utilities or MySQL libraries.
* The output format of the script can be freely chosen.


### Solution Rationale

The first decision one has to make when designing a solution to this exercise is to decide which script will be written in which language.
If the remote script were to be a shell script, it would have to run the optimization tasks, parse responses from the local MySQL server, 
count the successful table optimization operations and return appropriate responses to the management machine. 

Since concurrency in bash requires just a single line of code with the 'GNU Parallel' library and MySQL response processing in Python is trivial,
it is far more reasonable to write the first script in bash and the second script in Python, than vice versa.

Both scripts utilize concurrency where possible: the first script connects concurrently to each remote server to run the second script
and the second script starts a number of concurrent worker threads to process multiple matching databases in parallel.

The reason why each database is worked on by a single thread is to prevent Deadlocks which occur when multiple threads 
are trying to acquire locks on tables which have foreign keys with each other in the same database. 
This approach causes the optimization process to take slightly longer, but it prevents having to test 
the optimization results for Deadlock conditions and having to re-insert tables into the workload.

Due to the implemented concurrency, this solution is scalable for the optimization of 
large quantities of servers and databases in relatively short timeframes.
