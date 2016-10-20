# -*- encoding: utf-8 -*-
##############################################################################
#
#    open2bizz
#    Copyright (C) 2014 open2bizz (open2bizz.nl).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
"""
Created on 30-Apr-2015
Author S. Ferket

Test lock in psql: 
BEGIN ;
SELECT * FROM application_integration_data WHERE id=<the id> FOR UPDATE NOWAIT
"""
from openerp.osv import fields, osv
from openerp import api, models

import logging
import time
import threading
import openerp
import sys
import lxml.etree as etree
import random

_logger = logging.getLogger(__name__)

class DataThread (threading.Thread):
    def __init__(self, pool, db):
        self.pool = pool
        self.db = db
        self.uid = 1
        threading.Thread.__init__(self)
        _logger.info("DataThread started for database %s" % db)
    
        
    def run(self):
        while 1:
            time.sleep(random.random())

            _logger.debug('Run DataThread %s' % threading.currentThread())
            with api.Environment.manage():
                db = openerp.sql_db.db_connect(self.db)
                cr = db.cursor()
                appl_ids = self.pool.get('application.integration.application').search(cr,self.uid, [('active', '=', True)])
                cr.close()
                
                while True:
                    cr = db.cursor()
                    ids = self.pool.get('application.integration.data').search(cr,self.uid, [('state', '=', 'ready'), ('application', 'in', appl_ids)])
                    if len(ids) == 0:
                        cr.close()
                        break
                    obj = self.pool.get('application.integration.data').browse(cr, self.uid, ids[0])
                    
                    try:
                        lock_cr = db.cursor()
                        lock_cr.execute("""SELECT *
                                       FROM application_integration_data
                                       WHERE id=%s
                                       AND state ='ready'
                                       FOR UPDATE NOWAIT""" % obj.id
                                       , log_exceptions=False)
    
                        locked_job = lock_cr.fetchone()
                        
                        if not locked_job:
                            _logger.debug("Job `%s` already executed by another process/thread. skipping it", obj.id)
                            time.sleep(60)
                            continue
                    
                        try:
                            job_cr = db.cursor()
                            methodToCall = getattr(self.pool.get(obj.application.model), obj.application.function)
                            result = methodToCall(job_cr, self.uid,obj)
                            if result[0]:
                                self.pool.get('application.integration.data').write(lock_cr, self.uid, obj.id, {'state' : 'done', 'message' : result[1]})
                                job_cr.commit()
                                lock_cr.commit()
                            else:
                                self.pool.get('application.integration.data').write(lock_cr, self.uid, obj.id, {'state' : 'error', 'message' : result[1]})
                                job_cr.rollback()
                                lock_cr.commit()
                            
                        except:
                            if obj.application.function == False or obj.application.model == False:
                                _logger.error("Error calling method. No model or method specified." )
                            else:    
                                _logger.error("Error calling %s: %s - %s" % (obj.application.model+"."+obj.application.function ,sys.exc_info()[0], sys.exc_info()[1]) )
                            self.pool.get('application.integration.data').write(lock_cr, self.uid, obj.id, {'state' : 'error'})
                            job_cr.rollback()
                        finally:
                            lock_cr.commit()
                            job_cr.close()
                            #cr.close()

                            
                    except:
                        _logger.debug(("Error locking application.integration.data job: %s" % sys.exc_info()[1]))
                    finally:
                        lock_cr.close()  
                        cr.close()      

            _logger.debug('Stop processing DataThread %s' % threading.currentThread())
            time.sleep(60)


class application_integration_application(osv.osv):
    _name = "application.integration.application" 
    _description = "Application integration framework"
    
    _columns = { 
        'name': fields.char('Name', required=True),
        'description' : fields.text('Description'),
        'user_id': fields.many2one('res.users', 'User', required=True),
        'active': fields.boolean('Active', help="Not active means it will not process the records"),
        'model': fields.char('Object', help="Model name on which the method to be called is located, e.g. 'res.partner'."),
        'function': fields.char('Method', help="Name of the method to be called when this job is processed."),
        'args': fields.text('Arguments', help="Arguments to be passed to the method, e.g. (uid,)."),
        'priority': fields.integer('Priority', help='The priority of the job, as an integer: 0 means higher priority, 10 means lower priority.'),
        'checkpoint': fields.boolean('Checkpoint', help="Checked means we first create a checkpoint to be manually approved before processing"),
                }
    
    _sql_constraints = [
                        ('name_uniq', 'unique (name)', 'The name of asset must be unique!'),
                        ]

    
    
application_integration_application()

class application_integration_data(osv.osv):
    _name = "application.integration.data" 
    _inherit = 'mail.thread'
    _description = "Application integration framework data"
    
    def _make_data_pretty(self, cr, uid, ids, field_names, arg, context=None):
        res ={}
        for val in self.browse(cr, uid, ids, context=context):
            try:
                x = etree.fromstring(val.data)
                res[val.id] = etree.tostring(x, pretty_print = True) 
            except:
                res[val.id] = val.data    
        return res

    _columns = {
        'application':fields.many2one('application.integration.application', 'Application', required=True),
        'state':fields.selection([
            ('draft','Draft'),
            ('cancel','Cancelled'),
            ('ready','Ready for processing'),
            ('done','Done'),
            ('error','Error'),
             ],    'Status', select=True, readonly=True),
        'data' : fields.text('Data'),
        'message' : fields.text('Processing Message'),
        'pretty_data' : fields.function(_make_data_pretty, type='text', string='Pretty Data'),

    }
    
    def _attachfile(self,cr, uid , data, context=None):
        attachmentdata = {
                          'res_model': 'application.integration.data', #Model for the attachment
                          'res_id': data['res_id'], #id from the Model
                          'name' : data['filename'], #Filename
                          'datas' : data['file'], #Base64string from the file
                              }
        att_obj = self.pool.get('ir.attachment')
        att_obj.create(cr, uid, attachmentdata, {})
    
    def create(self, cr, uid, data, context=None):
        res = super(application_integration_data, self).create(cr, uid, data, context=context)
        if (data.get('file')!= None):
            data['res_id'] = res
            self._attachfile(cr,uid,data,context)
        return res
    
    def test_process(self, cr, uid, context=None):
        _logger.error('Test process')
        return [True, "Message OK"]

    def test_process2(self, cr, uid, context=None):
        _logger.error('Test process 2')
        raise Exception('spam', 'eggs') 
        return [False, "Message not ok"]
    

    
    
    def process(self, cr, uid, context=None):
        _logger.debug('Start processing')
        appl_ids = self.pool.get('application.integration.application').search(cr,uid, [('active', '=', True)])
        _logger.debug('Active applications found: %s' % appl_ids)
        data_ids = self.search(cr,uid, [('state', '=', 'ready'), ('application', 'in', appl_ids)])
        _logger.debug('Records to process found: %s' % data_ids)
        
        for obj in self.browse(cr,uid,data_ids, context = context):
            methodToCall = getattr(self.pool.get(obj.application.model), obj.application.function)
            _logger.error('Function: %s' % methodToCall)
            result = methodToCall(cr, uid)
            _logger.error('Result: %s' % result)
            
            _logger.debug('Process record: %s' % obj.id)      
            
        _logger.debug('Stop processing')
        
        return True

    def __init__(self, pool, cr):
        _logger.error("Thread started %s" % cr.dbname)
        #self.thread = DataThread(pool, cr) 
        self.thread = DataThread(pool, cr.dbname)
        self.thread.start()
        return  super(application_integration_data, self).__init__(pool, cr)

application_integration_data()  

from openerp import http
class TestSF(http.Controller):

    @http.route('/stefaan', type='http', auth="none")
    def index(self, s_action=None, db=None, **kw):
        return "Stefaan Ferket"


