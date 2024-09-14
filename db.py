import mysql.connector
import config

def connection_open():
    return mysql.connector.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME
    )

def db_update(sql, values):
    try:
        connection = connection_open()
        cursor = connection.cursor()
        cursor.execute(sql, values)
        connection.commit()

    except mysql.connector.Error as err:
        print(f"Error: {err}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def db_query(sql):
    try:
        connection = connection_open()
        cursor = connection.cursor()
        cursor.execute(sql)
        result = cursor.fetchall()
        return result

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def db_query_values(sql, values):
    try:
        connection = connection_open()
        cursor = connection.cursor()
        cursor.execute(sql, values)
        result = cursor.fetchall()
        return result

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
