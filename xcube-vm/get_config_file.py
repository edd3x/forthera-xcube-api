
import os
from azure.storage.blob import BlobServiceClient

print('Downloading xcube config file.....')
connection_string = os.environ.get('AzureWebJobsStorage')
# container_client = ContainerClient.from_connection_string(conn_str=connection_string, container_name='config-file')
blob_service_client_instance = BlobServiceClient.from_connection_string(conn_str=connection_string)
blob_client_instance = blob_service_client_instance.get_blob_client('config-file', 'xcube_config.yml', snapshot=None)
with open('/tmp/xcube_config.yml', "wb") as my_blob:
    blob_data = blob_client_instance.download_blob()
    blob_data.readinto(my_blob)

print('Config file downloaded succesfully...')
