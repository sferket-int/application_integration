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
Test lock in psql:
BEGIN ;
SELECT * FROM application_integration_data WHERE id=<the id> FOR UPDATE NOWAIT
"""
from openerp import models, fields, api, SUPERUSER_ID
from openerp.modules.registry import RegistryManager

import logging
import time
import threading
import sys
import lxml.etree as etree

_logger = logging.getLogger(__name__)


class ApplicationThread(threading.Thread):
    """
    Application Thread
    """

    def __init__(self, name, application_id, dbname, stopper):
        super(ApplicationThread, self).__init__(name=name)

        self.local = threading.local()

        self.local.name = name
        self.local.application_id = application_id
        self.local.dbname = dbname
        self.local.stopper = stopper

        # Set locals on thread object
        self.name = self.local.name
        self.application_id = self.local.application_id
        self.dbname = self.local.dbname
        self.stopper = self.local.stopper

        self.local.registry = RegistryManager.get(self.dbname)
        self.registry = self.local.registry

    def run(self):
        """
        Runs in a *new* database cursor
        """

        while not self.stopper.is_set():
            with api.Environment.manage(), self.new_db_cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                self.check_valid_application(env)
                self.process_application_data(env)

            time.sleep(60)
        return

    def new_db_cursor(self):
        return self.registry.cursor()

    def check_valid_application(self, env):
        application_model = env['application.integration.application']

        app_obj = application_model.search(
            [('id', '=', self.application_id)],
            limit=1
        )

        # Maybe application was removed while active thread.
        if not app_obj:
            _logger.info('Aborting Application Thread... No Application for Id: %s' % self.application_id)
            self.stopper.set()
            return

        # Maybe application was stopped while active thread.
        if app_obj and app_obj.thread_uuid is False:
            _logger.info('Aborting Application Thread... Application %s stopped' % app_obj.name)
            self.stopper.set()
            return

    def process_application_data(self, env):
        data_model = env['application.integration.data']
        objects = data_model.search(
            [('state', '=', 'ready'), ('application', '=', self.application_id)]
        )

        for obj in objects:
            # Stopper could be suddenly set!
            if self.stopper.is_set():
                return

            with self.new_db_cursor() as lock_cr:
                lock_env = api.Environment(lock_cr, SUPERUSER_ID, {})

                try:
                    lock_cr.execute(
                        """
                        SELECT
                          id
                        FROM
                          application_integration_data
                        WHERE
                          id = %s
                          AND state = 'ready'
                        FOR UPDATE NOWAIT""" % obj.id,
                        log_exceptions=False
                    )

                    locked_job = lock_cr.fetchone()

                    if not locked_job:
                        _logger.debug("Job `%s` already executed by another process/thread. skipping it", obj.id)
                        continue

                    try:
                        with self.new_db_cursor() as job_cr:
                            job_env = api.Environment(job_cr, SUPERUSER_ID, {})

                            _logger.info("Calling model.method: %s.%s" % (obj.application.model, obj.application.function))

                            method_to_call = getattr(job_env[obj.application.model], obj.application.function)
                            result = method_to_call(obj)

                            if result[0]:
                                obj.with_env(lock_env).write({'state': 'done', 'message': result[1]})
                                job_cr.commit()
                            else:
                                obj.with_env(lock_env).write({'state': 'error', 'message': result[1]})
                                job_cr.rollback()
                    except Exception as e:
                        if obj.application.function is not False or obj.application.model is not False:
                            _logger.error("Error %s", e)
                        else:
                            _logger.error(
                                "Error calling %s: %s - %s" %
                                (obj.application.model + "." + obj.application.function, sys.exc_info()[0], sys.exc_info()[1])
                            )

                        obj.with_env(lock_env).write({'state': 'error'})
                        job_cr.rollback()
                    finally:
                        lock_cr.commit()
                        job_cr.close()
                except:
                    _logger.info(("Error locking application.integration.data job: %s" % sys.exc_info()[1]))


class ApplicationIntegrationApplication(models.Model):
    _name = "application.integration.application"
    _description = "Application Integration Framework"

    name = fields.Char(
        "Name",
        required=True
    )
    description = fields.Text(
        "Description"
    )
    user_id = fields.Many2one(
        "res.users",
        "User",
        required=True
    )
    model = fields.Char(
        "Object",
        required=True,
        help="Model name on which the method to be called is located, e.g. 'res.partner'."
    )
    function = fields.Char(
        "Method",
        required=True,
        help="Name of the method to be called when this job is processed."
    )
    args = fields.Text(
        "Arguments",
        help="Arguments to be passed to the method, e.g. (uid,)."
    )
    priority = fields.Integer(
        "Priority",
        help="The priority of the job, as an integer: 0 means higher priority, 10 means lower priority."
    )
    checkpoint = fields.Boolean(
        "Checkpoint",
        help="Checked means we first create a checkpoint to be manually approved before processing",
    )
    thread_uuid = fields.Char(
        "UUID (thread)",
        compute='_thread_uuid',
        store=True
    )
    autostart = fields.Boolean(
        "Autostart",
        default=False,
        help="Ensures the application(thread) will be started right after Odoo starts"
    )

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'The name of asset must be unique!'),
    ]

    def __init__(self, pool, cr):
        res = super(ApplicationIntegrationApplication, self).__init__(pool, cr)
        self._autostart_application_threads(pool, cr)
        return res

    @api.multi
    def start_application_thread(self, context=None, *args, **kwargs):
        """Start application thread (button method)"""

        try:
            uuid = self._thread_uuid()
            self.thread_uuid = uuid

            dbname = self._cr.dbname

            self._cr.commit()

            self._start_application_thread(self.thread_uuid, self.id, dbname)
            return True
        except Exception, e:
            _logger.error('Exception: %s' % e)

    def _start_application_thread(self, thread_uuid, application_id, dbname):
        """Start application thread (thread handler)"""

        stopper = threading.Event()

        try:
            t = ApplicationThread(
                name=thread_uuid,
                application_id=application_id,
                dbname=dbname,
                stopper=stopper
            )
        except Exception as e:
            _logger.critical("Exception _start_application_thread: %s" % e)
            return

        _logger.info('Starting Application Integration thread: %s', thread_uuid)
        t.setDaemon(True)
        t.start()

    @api.multi
    def stop_application_thread(self, context=None, *args, **kwargs):
        """Stop application thread (button method)"""

        self._stop_application_thread(self.thread_uuid)
        self.thread_uuid = None
        self._cr.commit()

    def _stop_application_thread(self, thread_uuid):
        """Stop application thread (thread handler)"""

        for thread in threading.enumerate():
            if thread.getName() == thread_uuid:
                thread.stopper.set()
                _logger.info("Stopping Application Integration thread: %s", thread_uuid)
                # thread.join()  # TODO Needed?

    def is_thread_alive(self):
        if not self.thread_uuid:
            return False

        for thread in threading.enumerate():
            if thread.getName() == self.thread_uuid:
                return thread.is_alive()

        return False

    def _autostart_application_threads(self, pool, cr):
        """These (last resort) SQL could led to API-change breakage.  However,
        currently funky errors with ORM search/reads on
        odoo.api.Environment.
        """
        if not self._is_installed(pool, cr):
            return

        try:
            cr.execute(
                "SELECT "
                "    id, "
                "    autostart AS autostart,"
                "    thread_uuid AS uuid"
                "  FROM"
                "    application_integration_application "
                "  WHERE "
                "    autostart = True "
            )

            for (id, autostart, uuid) in cr.fetchall():
                # Stop
                self._stop_application_thread(uuid)
                cr.execute("UPDATE application_integration_application SET thread_uuid = NULL WHERE id = %s", (id,))
                # Start
                new_uuid = self._thread_uuid()
                self._start_application_thread(new_uuid, id, cr.dbname)
                cr.execute("UPDATE application_integration_application SET thread_uuid = %s WHERE id = %s", (str(new_uuid), id))

        except Exception, e:
            _logger.error("Exception: %s" % e)

    def _thread_uuid(self):
        from uuid import uuid4
        return uuid4()

    def _is_installed(self, pool, cr):
        cr.execute(
                "SELECT "
                "    1 "
                "  FROM"
                "    ir_module_module "
                "  WHERE "
                "    name = 'application_integration' "
                "    AND state = 'installed' "
            )

        return cr.fetchone() is not None


class ApplicationIntegrationData(models.Model):
    _name = "application.integration.data"
    _inherit = 'mail.thread'
    _description = "Application Integration Framework Data"

    application = fields.Many2one(
        'application.integration.application',
        "Application",
        required=True
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('cancel', 'Cancelled'),
            ('ready', 'Ready for processing'),
            ('done', 'Done'),
            ('error', 'Error')
        ],
        string="State",
        readonly=True
    )
    data = fields.Text(
        "Data"
    )
    message = fields.Text(
        'Processing Message'
    )
    pretty_data = fields.Text(
        'Pretty Data',
        _compute='_make_data_pretty'
    )

    @api.one
    def _make_data_pretty(self, id=None):
        try:
            x = etree.fromstring(self.data)
            self.pretty_data = etree.tostring(x, pretty_print=True)
        except:
            self.pretty_data = self.data

    @api.multi
    def _attachfile(self, vals):
        attachmentdata = {
            'res_model': 'application.integration.data',  # Model for the attachment
            'res_id': vals['res_id'],  # id from the Model
            'name': vals['filename'],  # Filename
            'datas': vals['file'],  # Base64string from the file
        }
        att_obj = self.env['ir.attachment']
        att_obj.create(attachmentdata)

    @api.model
    def create(self, vals):
        res = super(ApplicationIntegrationData, self).create(vals)
        if vals.get('file') is not None:
            vals['res_id'] = res
            self._attachfile(vals)
        return res

    def test_rapid_process(self, obj):
        msg = 'Test rapid process'
        _logger.error(msg)
        return [True, msg]

    def test_slow_process(self, obj):
        interval = 5
        msg = 'test slow process (%s seconds)' % interval
        _logger.error("Start: %s" % msg)
        time.sleep(interval)
        _logger.error("Done: %s" % msg)
        return [True, msg]

    def test_really_slow_process(self, obj):
        interval = 15
        msg = 'Test really slow process (%s seconds)' % interval
        _logger.error('Start: %s' % msg)
        time.sleep(interval)
        _logger.error('Done: %s' % msg)
        return [True, msg]

    def test_rapid_error_process(self, obj):
        msg = 'Test rapid error process'
        _logger.error(msg)
        return [False, msg]

    def test_slow_error_process(self, obj):
        interval = 10
        msg = 'Test slow error process: %s seconds' % interval
        _logger.error('Start: %s' % msg)
        time.sleep(interval)
        _logger.error('Done: %s' % msg)
        return [False, msg]
