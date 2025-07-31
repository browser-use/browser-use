from pymilvus import MilvusClient

client = MilvusClient(
    uri="http://localhost:8001",
    token="root:Milvus"
)
print("Milvusc 连接成功")

# client.create_database(
#     db_name="my_database_1"
# )
print(client.list_databases())