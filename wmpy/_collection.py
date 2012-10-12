""" wmpy collections

Many of these are slower than they need to be, but they do useful things.
"""
import collections
import operator
import types
import weakref

from . import _logging, watchable, weakmethod
_logger, _dbg, _info, _warn = _logging.get_logging_shortcuts(__name__)

# pylint: disable=E1102,W0212

class WatchableList(watchable.Mixin, object):
    def __init__(self, *args, **kw):
        watchable.Mixin.__init__(self)
        self._contents = list(*args, **kw)
    def __getitem__(self, idx):
        return self._contents[idx]
    def __len__(self):
        return len(self._contents)
    def __iter__(self):
        return iter(self._contents)

    def __setitem__(self, idx, value):
        if isinstance(idx, slice):
            value = list(value)
            idx_bounds = idx.indices(len(self))
            indices = range(*idx_bounds)
            if len(indices) == len(value):
                with self._event('update', idx=idx, new_value=value):
                    self._contents[idx] = value
            elif len(indices) > len(value):
                start, stop, step = idx_bounds
                if step != 1:
                    raise ValueError("shrinking extended slices unsupported")
                self[start:start+len(value)] = value
                del self[start+len(value):stop]
            else: # len(indices) < len(value), inserting elements
                start, stop, step = idx_bounds
                if step != 1:
                    raise ValueError("growing extended slices unsupported")
                insertPoint = start + len(indices)
                self[start:insertPoint] = value[:len(indices)]
                new_values = value[len(indices):]
                with self._event('insert', idx=insertPoint, values=new_values):
                    self._contents[insertPoint:insertPoint] = new_values
        else:
            with self._event('update', idx=idx, new_value=value):
                self._contents[idx] = value

    def __delitem__(self, idx):
        with self._event('del', idx=idx):
            del self._contents[idx]

    def append(self, value):
        with self._event('insert', idx=len(self), values=(value,)):
            self._contents.append(value)

    def extend(self, value):
        with self._event('insert', idx=len(self), values=value):
            self._contents.extend(value)

    def remove(self, value):
        for idx, my_value in enumerate(self._contents):
            if value == my_value:
                del self[idx]
                return
        raise ValueError("%r not in %s@%s",
            value, type(self), id(self))

class _ManyToManyCollection(#_logging.InstanceLoggingMixin,
                            object):
    inner = None
    _append = None
    _extend = None

    def __init__(self, my_idx, other_side, items = None):
        if items is None:
            items = self.inner()
        self._my_idx = my_idx
        self._other_side = other_side
        self._items = items
        self._link_all(items)
        self.listeners = []

    def add_weak_listener(self, cb):
        """ Adds a bound method to this object's listeners, such that
            the link will be broken if either self or cb.im_self is
            deallocated.
        """
        weak_cb = None
        def _remove_weak_listener(wself=weakref.ref(self)):
            wself = wself()
            if wself is None:
                return
            try:
                wself.listeners.remove(weak_cb)
            except ValueError:
                pass
        weak_cb = weakmethod(cb, _remove_weak_listener)
        self.listeners.append(weak_cb)
        return weak_cb

    def __index__(self, idx):
        return self._items[idx]
    def __len__(self):
        return len(self._items)
    def __iter__(self):
        return iter(self._items)
    def _notify(self):
        for func in self.listeners:
            func(self)
    def clear(self, notify=True):
        self._unlink_all(self._items)
        self._items = self.inner()
        if notify:
            self._notify()
    def _link(self, item, notify=True):
        self._other_side[item]._append(self._my_idx)
        if notify:
            #self._dbg('link %s notify %s', self._my_idx, item)
            self._other_side[item]._notify()
    def _link_all(self, items):
        items = list(items)
        for item in items:
            self._link(item, notify=False)
        for item in items:
            # do in second pass so notifications go out after
            # establishing consistency:
            #self._dbg('link all %s notify %s', self._my_idx, item)
            self._other_side[item]._notify()
    def _unlink(self, item, notify=True):
        self._other_side[item]._remove(self._my_idx)
        if notify:
            #self._dbg('unlink %s notify %s', self._my_idx, item)
            self._other_side[item]._notify()
    def _unlink_all(self, items):
        items = list(items)
        for item in items:
            self._unlink(item, notify=False)
        for item in items:
            #self._dbg('unlink all %s notify %s %x',
            #   self._my_idx, item, id(self._other_side[item]))
            self._other_side[item]._notify()
    def append(self, item):
        self._append(item)
        self._link(item)
        #self._dbg('append %s notify self', self._my_idx)
        self._notify()
    def extend(self, items):
        self._extend(items)
        self._link_all(items)
        #self._dbg('extend %s notify self', self._my_idx)
        self._notify()
    def _remove(self, item):
        self._items.remove(item)
    def remove(self, item):
        self._remove(item)
        self._unlink(item)
        self._notify()
    def _replace(self, newitems):
        self.clear(notify=False)
        self.extend(newitems)
        return self
    def _op(name):  # pylint: disable=E0213
        op = getattr(operator, name)
        def do_op(self, other):
            #_dbg('op %s %s %s', self, op, other)
            if isinstance(other, _ManyToManyCollection):
                return op(self._items, other._items)
            else:
                return op(self._items, other)
        def do_iop(self, other):
            newitems = op(self, other)
            return self._replace(newitems)
        do_op.__name__ = name
        do_iop.__name__ = '__i' + name[2:]
        return do_op, do_iop
    __add__, __iadd__ = _op('__add__')
    __and__,__iand__ = _op('__and__')
    __or__,__ior__ = _op('__or__')
    __xor__,__ixor__ = _op('__xor__')

    def __str__(self):
        return repr(self)
    def __repr__(self):
        return '<%s(%r)>' % (type(self).__name__, self._items)

class _MMList(_ManyToManyCollection):
    inner = list
    def _append(self, item):
        self._items.append(item)
    def _extend(self, items):
        self._items.extend(items)
    def __getitem__(self, idx):
        return self._items[idx]
    def __setitem__(self, idx, new_item):
        if isinstance(idx, slice):
            self._unlink_all(self._items[idx])
        else:
            self._unlink(self._items[idx])
        self._items[idx] = new_item
        if isinstance(idx, slice):
            self._link_all(new_item)
        else:
            self._link(new_item)
        #self._dbg('setitem %s notify self', self._my_idx)
        self._notify()
    def __delitem__(self, idx):
        if isinstance(idx, slice):
            self._unlink_all(self._items[idx])
        else:
            self._unlink(self._items[idx])
        del self._items[idx]
        #self._dbg('delitem %s notify self', self._my_idx)
        self._notify()

class _MMCheckedList(_MMList):
    @classmethod
    def _setup(cls):
        for k, v in list(_MMList.__dict__.items()):
            if isinstance(v, types.FunctionType):
                _dbg('adding uniqueness check to %s.%s', cls.__name__, k)
                def make_check_and_do(k=k, v=v):
                    def check_and_do(self, *args, **kw):
                        #_dbg('doing uniqueness check for %s.%s',
                        #   cls.__name__, k)
                        rv = v(self, *args, **kw)
                        self._check('after ' + k)
                        return rv
                    check_and_do.__name__ = k + '_and_check'
                    return check_and_do
                setattr(cls, k, make_check_and_do())
        del cls._setup

    def _check(self, when):
        dupes = collections.Counter(self._items) - \
                collections.Counter(set(self._items))
        if len(dupes) > 0:
            raise ValueError(
                'duplicates detected in list check %s: %s'
                % (when, list(dupes.elements())))

_MMCheckedList._setup()

class _MMSet(_ManyToManyCollection):
    inner = set
    def _append(self, item):
        self._items.add(item)
    def _extend(self, items):
        self._items.update(items)
    def _replace(self, newitems):
        self._unlink_all(self._items - newitems)
        self._link_all(newitems - self._items)
        self._items = newitems
        #self._dbg('_replace %s notify self', self._my_idx)
        self._notify()
        return self
    # override append and extend to not add redundant links for existing items:
    def append(self, item):
        if item in self:
            return
        _ManyToManyCollection.append(self, item)
    def extend(self, items):
        items = set(items) - self._items
        _ManyToManyCollection.extend(self, items)

class _MMCounter(_ManyToManyCollection):
    inner = collections.Counter
    def _append(self, item):
        self._items.update((item,))
    def _extend(self, items):
        self._items.update(items)
    def _remove(self, item):
        self._items.subtract((item,))
    def _replace(self, newitems):
        self._unlink_all((self._items - newitems).elements())
        self._link_all((newitems - self._items).elements())
        self._items = newitems
        #self._dbg('_replace %s notify self', self._my_idx)
        self._notify()
        return self
    def __iter__(self):
        return iter(self._items.elements())

class _ManyToManySide(object):
    kinds = {
        'checked_list': _MMCheckedList,
        'counter': _MMCounter,
        'list': _MMList,
        'set': _MMSet,
    }

    def __init__(self, kind, other=None):
        self._kind = self.kinds[kind]
        self._contents = {}
        if other is not None:
            self._other = weakref.proxy(other)

    def set_other(self, new_other):
        self._other = weakref.proxy(new_other)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            raise TypeError
        if idx not in self._contents:
            self._contents[idx] = self._kind(idx, self._other)
        return self._contents[idx]

    def __setitem__(self, idx, items):
        if self[idx] is items:
            return
        items = self._kind.inner(items)
        self[idx]._replace(items)

    def __delitem__(self, idx):
        if isinstance(idx, slice):
            raise TypeError
        self._contents.pop(idx).clear()

    def __len__(self):
        return len(self._contents)
    def __iter__(self):
        return iter(self._contents.items())
    def keys(self):
        return iter(self._contents.keys())
    def values(self):
        return iter(self._contents.values())
    def items(self):
        return iter(self._contents.items())

class ManyToMany(object):
    def __init__(self, left_kind='set', right_kind='set'):
        self.left = _ManyToManySide(left_kind)
        self.right = _ManyToManySide(right_kind, self.left)
        self.left.set_other(self.right)

    def __iter__(self):
        return iter((self.left, self.right))

