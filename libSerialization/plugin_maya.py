import pymel.core as pymel
from maya import OpenMaya
import logging
import consts
import core
import decorators

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

def is_valid_PyNode(val):
    return val and hasattr(val, 'exists') and val.exists()


#
# Maya Metanetwork Serialization
#

class MayaSerializer(core.DictSerializer):
    # TODO: Add support for OpenMaya datatypes
    types_dag = [
        pymel.PyNode,
        pymel.Attribute,
        pymel.datatypes.Matrix,
        pymel.datatypes.Vector

    ]

    def is_data_pymel(self, data):
        """
        Add pymel support.
        """
        return any(filter(lambda x: isinstance(data, x), iter(self.types_dag)))

    def get_data_type(self, data):
        # It is important to check pymel data before complex data since basically,
        # pymel.PyNode and pymel.PyNode are complex datatypes themselfs.
        if self.is_data_pymel(data):
            return consts.DataTypes.TYPE_DAGNODE
        return super(MayaSerializer, self).get_data_type(data)

    def create_attr(self, name, data):
        if isinstance(data, basestring):
            fn = OpenMaya.MFnTypedAttribute()
            fn.create(name, name, OpenMaya.MFnData.kString)
            return fn
        data_type = type(data)
        if issubclass(data_type, bool):
            fn = OpenMaya.MFnNumericAttribute()
            fn.create(name, name, OpenMaya.MFnNumericData.kBoolean)
            return fn
        if issubclass(data_type, int):
            fn = OpenMaya.MFnNumericAttribute()
            fn.create(name, name, OpenMaya.MFnNumericData.kInt)
            return fn
        if issubclass(data_type, float):
            fn = OpenMaya.MFnNumericAttribute()
            fn.create(name, name, OpenMaya.MFnNumericData.kFloat)
            return fn
        if isinstance(data, dict):
            fn = OpenMaya.MFnMessageAttribute()
            fn.create(name, name)
            return fn
        if isinstance(data, list) or isinstance(type, tuple):
            if len(data) < 1:
                pymel.warning("Can't create attribute {0}, empty array are unsuported".format(name))
                return None
            # TODO: Throw error when the array have multiple types
            fn = self.create_attr(name, data[0])
            fn.setArray(True)
            return fn
        if issubclass(data_type, pymel.datatypes.Matrix):  # HACK
            fn = OpenMaya.MFnMatrixAttribute()
            fn.create(name, name)
            return fn
        if issubclass(data_type, pymel.datatypes.Vector):
            name_x = '{0}X'.format(name)
            name_y = '{0}Y'.format(name)
            name_z = '{0}Z'.format(name)
            fn = OpenMaya.MFnNumericAttribute()
            mo_x = fn.create(name_x, name_x, OpenMaya.MFnNumericData.kDouble)
            mo_y = fn.create(name_y, name_y, OpenMaya.MFnNumericData.kDouble)
            mo_z = fn.create(name_z, name_z, OpenMaya.MFnNumericData.kDouble)
            fn.create(name, name, mo_x, mo_y, mo_z)
            return fn
        if issubclass(data_type, pymel.Attribute):
            if not is_valid_PyNode(data):
                log.warning("Can't serialize {0} attribute because of non-existent pymel Attribute!".format(name))
                return None
            elif data.type() == 'doubleAngle':
                fn = OpenMaya.MFnUnitAttribute()
                fn.create(name, name, OpenMaya.MFnUnitAttribute.kAngle)
                return fn
            elif data.type() == 'time':
                fn = OpenMaya.MFnUnitAttribute()
                fn.create(name, name, OpenMaya.MFnUnitAttribute.kTime)
                return fn
            # elif _val.type() == '???':
            #    fn = OpenMaya.MFnUnitAttribute()
            #    fn.create(_name, _name, OpenMaya.MFnUnitAttribute.kDistance)
            #    return fn
            # If the attribute doesn't represent anything special,
            # we'll check it's value to know what attribute type to create.
            else:
                return self.create_attr(name, data.get())
        if hasattr(data, '__melobject__'):  # TODO: Really usefull?
            fn = OpenMaya.MFnMessageAttribute()
            fn.create(name, name)
            return fn
        if hasattr(data, '__dict__'):
            fn = OpenMaya.MFnMessageAttribute()
            fn.create(name, name)
            return fn
        pymel.error("Can't create MFnAttribute for {0} {1} {2}".format(name, data, data_type))

    def add_attr(self, mfn_DependNode, name, data):
        data_type = self.get_data_type(data)

        # Skip empty list
        is_multi = data_type == consts.DataTypes.TYPE_LIST
        if is_multi and len(data) == 0:
            return

        plug = None
        # Get attribute arguments
        try:  # TODO: Is a try/catch really the best way to know if the plug exists?
            plug = mfn_DependNode.findPlug(name)
        except:
            pass

        if plug is None:
            att_mfn = self.create_attr(name, data)
            if att_mfn is None:
                return  # In case of invalid value like missing pymel PyNode & Attributes
            att_mfn.setNiceNameOverride(name)
            att_mo = att_mfn.object()
            if att_mo is not None:
                try:
                    mfn_DependNode.addAttribute(att_mo)
                    plug = OpenMaya.MPlug(mfn_DependNode.object(), att_mo)
                except Exception as e:
                    log.warning('Error adding attribute {0}: {1}'.format(name, e))

        if plug is not None:
            self.set_attr(plug, data)

    def set_attr(self, plug, data):
        data_type = self.get_data_type(data)
        if data_type == consts.DataTypes.TYPE_LIST:
            num_elements = len(data)

            plug.setNumElements(num_elements)  # TODO: MAKE IT WORK # TODO: NECESSARY???

            for i in range(num_elements):
                self.set_attr(plug.elementByLogicalIndex(i), data[i])

        elif data_type == consts.DataTypes.TYPE_BASIC:
            # Basic types
            if isinstance(data, bool):
                plug.setBool(data)
            elif isinstance(data, int):
                plug.setInt(data)
            elif isinstance(data, float):
                plug.setFloat(data)
            elif isinstance(data, basestring):
                plug.setString(data)
                # pymel.Attribute(_plug).set(_val)

        elif data_type == consts.DataTypes.TYPE_COMPLEX:
            network = self.export_network(data)
            plug = network.__apimfn__().findPlug('message')

            # Use a dag modifier to connect the attribute. TODO: Is this really the best way?
            dagM = OpenMaya.MDagModifier()
            dagM.connect(plug, plug)
            dagM.doIt()

        elif data_type == consts.DataTypes.TYPE_DAGNODE:
            plug = None
            if isinstance(data, pymel.Attribute):  # pymel.Attribute
                # Hack: Don't crash with non-existent pymel.Attribute
                if not data.exists():
                    log.warning("Can't setAttr, Attribute {0} don't exist".format(data))
                    return
                plug = data.__apimfn__()
            elif isinstance(data, pymel.datatypes.Matrix):
                fn = OpenMaya.MFnMatrixData()
                mo = fn.create(data.apicls(data))
                plug.setMObject(mo)
                return True
            elif isinstance(data, pymel.datatypes.Vector):
                plug.child(0).setFloat(data.x)
                plug.child(1).setFloat(data.y)
                plug.child(2).setFloat(data.z)
                return True
            elif hasattr(data, 'exists'):  # pymel.PyNode
                # Hack: Don't crash with non-existent pymel.Attribute
                if not pymel.objExists(data.__melobject__()):
                    log.warning("Can't setAttr, PyNode {0} don't exist".format(data))
                    return
                plug = data.__apimfn__().findPlug('message')

            if plug is not None:
                dagM = OpenMaya.MDagModifier()
                # if pymel.attributeQuery(pymel.Attribute(_val), writable=True):
                dagM.connect(plug, plug)
                dagM.connect(plug, plug)  # is connecting two times necessary?
                dagM.doIt()
            else:
                raise Exception("Unknow TYPE {0}, {1}".format(type(data), data))

        else:
            print data, data_type
            raise NotImplementedError

    def get_network_attr(self, attr):
        # Recursive
        if attr.isMulti():
            return [self.get_network_attr(attr.elementByPhysicalIndex(i)) for i in range(attr.numElements())]

        if attr.type() == 'message':
            if not attr.isConnected():
                log.warning('[_getNetworkAttr] Un-connected message attribute, skipping {0}'.format(attr))
                return None
            attr_input = attr.inputs()[0]
            # Network
            if hasattr(attr_input, '_class'):
                return self.import_network(attr_input)
            # Node
            else:
                return attr_input

        # pymel.Attribute
        if attr.isConnected():
            return attr.inputs(plugs=True)[0]

        # Basic type
        return attr.get()

    def export_network(self, data, **kwargs):
        #log.debug('CreateNetwork {0}'.format(data))

        # We'll deal with two additional attributes, '_network' and '_uid'.
        # Thoses two attributes allow us to find the network from the value and vice-versa.
        # Note that since the '_uid' refer to the current python context,
        # it's value could be erroned when calling import_network.
        # However the change of collisions are extremely improbable so checking the type of the python variable
        # is sufficient.
        # Please feel free to provide a better design if any if possible.

        # Optimisation: Use existing network if already present in scene
        if hasattr(data, '_network') and is_valid_PyNode(data._network):
            network = data._network
        else:
            # Automaticly name network whenever possible
            try:
                network_name = data.__getNetworkName__()
            except (AttributeError, TypeError):
                network_name = data.__class__.__name__

            network = pymel.createNode('network', name=network_name)

            # Monkey patch the network in a _network attribute if supported.
            if isinstance(data, object) and not isinstance(data, dict):
                data._network = network

        # Ensure the network have the current python id stored
        if not network.hasAttr('_uid'):
            pymel.addAttr(network, longName='_uid', niceName='_uid', at='long')  # todo: validate attributeType
        #    network._uid.set(id(_data))

        # Convert _pData to basic data dictionary (recursive for now)
        data_dict = self.export_dict(data, recursive=False, **kwargs)
        assert (isinstance(data_dict, dict))

        fnNet = network.__apimfn__()
        for key, val in data_dict.items():
            if val is not None:
                if key == '_class' or key[0] != '_':  # Attributes starting with '_' are protected or private
                    self.add_attr(fnNet, key, val)

        return network

    # Define constants
    _attr_name_class = '_class'
    _attr_name_module = '_class_module'

    # todo: add an optimisation to prevent recreating the python variable if it already exist.
    def import_network(self, network, module=None):
        if not network.hasAttr('_class'):
            log.error('[importFromNetwork] Network dont have mandatory attribute _class')
            raise AttributeError

        class_name = network.getAttr(self._attr_name_class)
        class_module = network.getAttr(self._attr_name_module) if network.hasAttr(self._attr_name_module) else None
        cls = self._get_class_by_name(class_name, class_module)
        if cls is None:
            return None

        obj = cls()

        # Monkey patch the network if supported
        if isinstance(obj, object) and not isinstance(obj, dict):
            obj._network = network

        # Resolve wich attribute we'll want to import
        attrs_by_longname = {}
        for attr_name in pymel.listAttr(network, userDefined=True):
            if '_' != attr_name[0]:  # Attribute longName starting with '_' are considered private
                attrs_by_longname[attr_name] = network.attr(attr_name)

        # Filter compound children as we are only interested the compound value itself.
        # ex: import translate and skip translateX, translateY, translateZ
        for attr in attrs_by_longname.values():
            if attr.isCompound():
                for child in attr.getChildren():
                    child_longname = child.longName()
                    try:
                        attrs_by_longname.pop(child_longname)
                    except KeyError:
                        pass

        for attr_name, attr in attrs_by_longname.iteritems():
            # logging.debug('Importing attribute {0} from {1}'.format(key, _network.name()))
            val = self.get_network_attr(attr)
            # if hasattr(obj, key):
            if isinstance(obj, dict):
                obj[attr_name.longName()] = val
            else:
                setattr(obj, attr_name, val)
            # else:
            #    #logging.debug("Can't set attribute {0} to {1}, attribute does not exists".format(key, obj))

            # Update network _uid to the current python variable context
            #    if _network.hasAttr('_uid'):
            #        _network._uid.set(id(obj))

        # Hack: Find implemented class via duck-typing
        # Implement a __callbackNetworkPostBuild__ method in your class instances as a callback.
        try:
            obj.__callbackNetworkPostBuild__()
        except (AttributeError, TypeError):
            pass

        return obj

#
# Global methods
#

__all__ = ['export_network', 'import_network', 'getConnectedNetworks', 'getConnectedNetworksByHierarchy',
           'getNetworksByClass', 'isNetworkInstanceOfClass']


def export_network(data, base_class=object, module=None, **kwargs):
    s = MayaSerializer(base_class=base_class, module=module)
    s.export_network(data, **kwargs)

@decorators.profiler
def import_network(network, base_class=object, module=None, **kwargs):
    s = MayaSerializer(base_class=base_class, module=module)
    return s.import_network(network, **kwargs)


def isNetworkInstanceOfClass(_network, cls_name):
    return hasattr(_network, '_class') and cls_name in _network._class.get().split('.')


def getNetworksByClass(_clsName):
    return [network for network in pymel.ls(type='network') if isNetworkInstanceOfClass(network, _clsName)]


# TODO: benchmark with sets
def getConnectedNetworks(objs, key=None, recursive=True, inArray=None):
    # Initialise the array the first time, we don't want to do it in the function argument as it will keep old values...
    if inArray is None:
        inArray = []

    if not hasattr(objs, '__iter__'):
        objs = [objs]

    for obj in objs:
        if hasattr(obj, 'message'):
            for output in obj.message.outputs():
                if isinstance(output, pymel.nodetypes.Network):
                    if output not in inArray:
                        if key is None or key(output):
                            inArray.append(output)
                        if recursive:
                            getConnectedNetworks(output, key=key, recursive=recursive, inArray=inArray)
    return inArray


# Return all connected network while traversing the hierarchy upward.
# The last result will be the higher in the hierarchy.
# Mainly used to get parent autorig network
def getConnectedNetworksByHierarchy(obj, recursive=False, **kwargs):
    networks = set()
    while obj is not None:
        for current_network in getConnectedNetworks(obj, recursive=recursive, **kwargs):
            networks.add(current_network)
        obj = obj.getParent()
    return list(networks)
