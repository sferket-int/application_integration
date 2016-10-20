'''
Created on Apr 29, 2014

@author: ferkets
'''
import xmlrpclib
import base64

server='http://localhost:8069' 
username = 'admin' #the user
pwd = 'admin'      #the password of the user
# dbname = 'application_integration_v8'    #the database
dbname = 'apl_int'    #the database

sock_common = xmlrpclib.ServerProxy (server + '/xmlrpc/common')
uid = sock_common.login(dbname, username, pwd)
print uid

sock = xmlrpclib.ServerProxy(server + '/xmlrpc/object')
xmlfile = "/home/jordy/Documenten/134 Artikelen 20150529.xml"
base64string = str(open(xmlfile,"rb").read().encode('base64'))

args = {'application':1,
        'state': 'ready',
        'data' : "bla bla",
       #beneath code is for adding a file
        'file' : base64string,
        'filename' : "Hallooooo2.xml"

#        'message' : fields.text('Processing Message'), 
}
rec = sock.execute(dbname, uid, pwd, 'application.integration.data', 'create', args)
print rec

#rec = sock.execute(dbname, uid, pwd, 'application.integration.data', 'process')
#print rec












