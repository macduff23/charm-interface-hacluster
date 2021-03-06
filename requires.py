#!/usr/bin/python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import hashlib

import relations.hacluster.common
from charms.reactive import hook
from charms.reactive import RelationBase
from charms.reactive import scopes
from charms.reactive.helpers import data_changed
from charmhelpers.core import hookenv


class HAClusterRequires(RelationBase):
    # The hacluster charm is a subordinate charm and really only works
    # for a single service to the HA Cluster relation, therefore set the
    # expected scope to be GLOBAL.
    scope = scopes.GLOBAL

    @hook('{requires:hacluster}-relation-joined')
    def joined(self):
        self.set_state('{relation_name}.connected')

    @hook('{requires:hacluster}-relation-changed')
    def changed(self):
        if self.is_clustered():
            self.set_state('{relation_name}.available')
        else:
            self.remove_state('{relation_name}.available')

    @hook('{requires:hacluster}-relation-{broken,departed}')
    def departed(self):
        self.remove_state('{relation_name}.available')
        self.remove_state('{relation_name}.connected')

    def is_clustered(self):
        """Has the hacluster charm set clustered?

        The hacluster charm sets cluster=True when it determines it is ready.
        Check the relation data for clustered and force a boolean return.

        :returns: boolean
        """
        clustered_values = self.get_remote_all('clustered')
        if clustered_values:
            # There is only ever one subordinate hacluster unit
            clustered = clustered_values[0]
            # Future versions of hacluster will return a bool
            # Current versions return a string
            if type(clustered) is bool:
                return clustered
            elif (clustered is not None and
                    (clustered.lower() == 'true' or
                     clustered.lower() == 'yes')):
                return True
        return False

    def bind_on(self, iface=None, mcastport=None):
        relation_data = {}
        if iface:
            relation_data['corosync_bindiface'] = iface
        if mcastport:
            relation_data['corosync_mcastport'] = mcastport

        if relation_data and data_changed('hacluster-bind_on', relation_data):
            self.set_local(**relation_data)
            self.set_remote(**relation_data)

    def manage_resources(self, crm):
        """
        Request for the hacluster to manage the resources defined in the
        crm object.

            res = CRM()
            res.primitive('res_neutron_haproxy', 'lsb:haproxy',
                          op='monitor interval="5s"')
            res.init_services('haproxy')
            res.clone('cl_nova_haproxy', 'res_neutron_haproxy')

            hacluster.manage_resources(crm)

        :param crm: CRM() instance - Config object for Pacemaker resources
        :returns: None
        """
        relation_data = {
            'json_{}'.format(k): json.dumps(v, sort_keys=True)
            for k, v in crm.items() if v
        }
        if data_changed('hacluster-manage_resources', relation_data):
            self.set_local(**relation_data)
            self.set_remote(**relation_data)

    def bind_resources(self, iface=None, mcastport=None):
        """Inform the ha subordinate about each service it should manage. The
        child class specifies the services via self.ha_resources

        :param iface: string - Network interface to bind to
        :param mcastport: int - Multicast port corosync should use for cluster
                                management traffic
        """
        if mcastport is None:
            mcastport = 4440
        resources_dict = self.get_local('resources')
        self.bind_on(iface=iface, mcastport=mcastport)
        if resources_dict:
            resources = relations.hacluster.common.CRM(**resources_dict)
            self.manage_resources(resources)

    def delete_resource(self, resource_name):
        resource_dict = self.get_local('resources')
        if resource_dict:
            resources = relations.hacluster.common.CRM(**resource_dict)
        else:
            resources = relations.hacluster.common.CRM()
        resources.add_delete_resource(resource_name)
        self.set_local(resources=resources)

    def add_vip(self, name, vip, iface=None, netmask=None):
        """Add a VirtualIP object for each user specified vip to self.resources

        :param name: string - Name of service
        :param vip: string - Virtual IP to be managed
        :param iface: string - Network interface to bind vip to
        :param netmask: string - Netmask for vip
        :returns: None
        """
        resource_dict = self.get_local('resources')
        if resource_dict:
            resources = relations.hacluster.common.CRM(**resource_dict)
        else:
            resources = relations.hacluster.common.CRM()
        resources.add(
            relations.hacluster.common.VirtualIP(
                name,
                vip,
                nic=iface,
                cidr=netmask,))

        # Vip Group
        group = 'grp_{}_vips'.format(name)
        vip_res_group_members = []
        if resource_dict:
            vip_resources = resource_dict.get('resources')
            if vip_resources:
                for vip_res in vip_resources:
                    if 'vip' in vip_res:
                        vip_res_group_members.append(vip_res)
                resources.group(group,
                                *sorted(vip_res_group_members))

        self.set_local(resources=resources)

    def remove_vip(self, name, vip, iface=None):
        """Remove a virtual IP

        :param name: string - Name of service
        :param vip: string - Virtual IP
        :param iface: string - Network interface vip bound to
        """
        if iface:
            nic_name = iface
        else:
            nic_name = hashlib.sha1(vip.encode('UTF-8')).hexdigest()[:7]
        self.delete_resource('res_{}_{}_vip'.format(name, nic_name))

    def add_init_service(self, name, service, clone=True):
        """Add a InitService object for haproxy to self.resources

        :param name: string - Name of service
        :param service: string - Name service uses in init system
        :returns: None
        """
        resource_dict = self.get_local('resources')
        if resource_dict:
            resources = relations.hacluster.common.CRM(**resource_dict)
        else:
            resources = relations.hacluster.common.CRM()
        resources.add(
            relations.hacluster.common.InitService(name, service, clone))
        self.set_local(resources=resources)

    def remove_init_service(self, name, service):
        """Remove an init service

        :param name: string - Name of service
        :param service: string - Name of service used in init system
        """
        res_key = 'res_{}_{}'.format(
            name.replace('-', '_'),
            service.replace('-', '_'))
        self.delete_resource(res_key)

    def add_systemd_service(self, name, service, clone=True):
        """Add a SystemdService object to self.resources

        :param name: string - Name of service
        :param service: string - Name service uses in systemd
        :returns: None
        """
        resource_dict = self.get_local('resources')
        if resource_dict:
            resources = relations.hacluster.common.CRM(**resource_dict)
        else:
            resources = relations.hacluster.common.CRM()
        resources.add(
            relations.hacluster.common.SystemdService(name, service, clone))
        self.set_local(resources=resources)

    def remove_systemd_service(self, name, service):
        """Remove a systemd service

        :param name: string - Name of service
        :param service: string - Name of service used in systemd
        """
        res_key = 'res_{}_{}'.format(
            name.replace('-', '_'),
            service.replace('-', '_'))
        self.delete_resource(res_key)

    def add_dnsha(self, name, ip, fqdn, endpoint_type):
        """Add a DNS entry to self.resources

        :param name: string - Name of service
        :param ip: string - IP address dns entry should resolve to
        :param fqdn: string - The DNS entry name
        :param endpoint_type: string - Public, private, internal etc
        :returns: None
        """
        resource_dict = self.get_local('resources')
        if resource_dict:
            resources = relations.hacluster.common.CRM(**resource_dict)
        else:
            resources = relations.hacluster.common.CRM()
        resources.add(
            relations.hacluster.common.DNSEntry(name, ip, fqdn, endpoint_type))

        # DNS Group
        group = 'grp_{}_hostnames'.format(name)
        dns_res_group_members = []
        if resource_dict:
            dns_resources = resource_dict.get('resources')
            if dns_resources:
                for dns_res in dns_resources:
                    if 'hostname' in dns_res:
                        dns_res_group_members.append(dns_res)
                resources.group(group,
                                *sorted(dns_res_group_members))

        self.set_local(resources=resources)

    def remove_dnsha(self, name, endpoint_type):
        """Remove a DNS entry

        :param name: string - Name of service
        :param endpoint_type: string - Public, private, internal etc
        :returns: None
        """
        res_key = 'res_{}_{}_hostname'.format(
            self.service_name.replace('-', '_'),
            self.endpoint_type)
        self.delete_resource(res_key)

    def get_remote_all(self, key, default=None):
        """Return a list of all values presented by remote units for key"""
        values = []
        for conversation in self.conversations():
            for relation_id in conversation.relation_ids:
                for unit in hookenv.related_units(relation_id):
                    value = hookenv.relation_get(key,
                                                 unit,
                                                 relation_id) or default
                    if value:
                        values.append(value)
        return list(set(values))
