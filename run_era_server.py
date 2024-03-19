from azure.storage.blob import BlobServiceClient
import subprocess
import logging
import os

print('Downloading xcube config file.....')
connection_string = os.environ.get('AzureWebJobsStorage')
blob_service_client_instance = BlobServiceClient.from_connection_string(conn_str=connection_string)
blob_client_instance = blob_service_client_instance.get_blob_client('config-file', 'xcube_config.yml', snapshot=None)
with open(file='xcube_config.yml', mode="wb") as config_blob:
    blob_data = blob_client_instance.download_blob()
    config_blob.write(blob_data.readall())
    

print('Config file downloaded succesfully...')

subprocess.run('xcube serve --port 8082 --config xcube_config.yml -v', shell=True)