import pymysql

conn = pymysql.connect(
    host="127.0.0.1",
    user="root",
    password="",
    database="photosharing",
    port=3307  # same port as XAMPP
)

print("Connected OK")
