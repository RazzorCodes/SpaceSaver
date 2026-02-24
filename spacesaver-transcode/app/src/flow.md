1. Load database:
    1.1 check database exists
        1.1.1 if it does not, create it
    1.2 check database is valid
        1.2.1 if it is not valid, delete it and create a new one
    1.3 load database
2. Handle work in-progress
    2.1 Query database for work in-progress
    2.2 Check the status of the work in-progress
        2.2.1 Recoverable: Work was completed, copy | db update failed
        2.2.2 Unrecoverable: Work was not completed
    2.3 Recover if possible -> copy, set db as done, delete original
        Checks to be done
          - origial hash matches what the file is broadcasting
          - file format is correct or acceptable
          - file is smaller than original
    2.4 Delete unrecoverable, re-enqueue for work

3. Scan media folder
    3.1 Handle duplicated media -> case 2.2 but delete failed
    3.2 Add files not already existent to the db

4. Await work task
