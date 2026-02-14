import pymysql

def get_db_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="",          # put password if you have one
        database="photosharing",
        port=3307,
        cursorclass=pymysql.cursors.DictCursor
    )
