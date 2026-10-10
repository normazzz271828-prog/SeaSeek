"""Remove byte-identical result copies. Back up the database before running."""
import argparse
import sqlite3
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('database',type=Path)
    args=parser.parse_args()
    if not args.database.is_file():raise SystemExit('Database does not exist')
    con=sqlite3.connect(args.database,timeout=30)
    with con:
        count=con.execute('UPDATE analyses SET result=NULL WHERE result=original').rowcount
    # Reclaim unused BLOB pages; no identifiers or business records are removed.
    con.execute('VACUUM')
    con.close()
    print(f'Deduplicated {count} image results')

if __name__=='__main__':main()
