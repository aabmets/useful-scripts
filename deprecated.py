# ====================================================================================== #
#                                                                                        #
#   MIT License                                                                          #
#                                                                                        #
#   Copyright (c) 2022 - Mattias Aabmets                                                 #
#                                                                                        #
#   Permission is hereby granted, free of charge, to any person obtaining a copy         #
#   of this software and associated documentation files (the "Software"), to deal        #
#   in the Software without restriction, including without limitation the rights         #
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell            #
#   copies of the Software, and to permit persons to whom the Software is                #
#   furnished to do so, subject to the following conditions:                             #
#                                                                                        #
#   The above copyright notice and this permission notice shall be included in all       #
#   copies or substantial portions of the Software.                                      #
#                                                                                        #
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR           #
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,             #
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE          #
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER               #
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,        #
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE        #
#   SOFTWARE.                                                                            #
#                                                                                        #
# ====================================================================================== #
from typing import Union, Callable
from pathlib import Path
import traceback
import warnings
import inspect


warnings.filterwarnings('always', category=DeprecationWarning)
DepType = Union[property, Callable]


# ====================================================================================== #
def deprecated(old_name: str, obj: DepType) -> DepType:
    """
    This decorator can wrap either a property, a function
    or a class object with a deprecation warning.

    :param old_name: The old deprecated name of the object.
    :param obj: The object to be wrapped with a deprecation warning.
    :return: A decorated property, function or a class.
    """

    # -------------------------------------------------------- #
    def warn(obj_type: str):
        msg = f'\nWARNING! {obj_type} name \'{old_name}\' is ' \
              f'deprecated! Replace it with \'{new_name}\'!'
        tb = traceback.extract_stack()[0]
        file = Path(tb.filename)
        warnings.warn_explicit(
            message=msg,
            category=DeprecationWarning,
            filename=file.name,
            lineno=tb.lineno
        )

    # -------------------------------------------------------- #
    if isinstance(obj, property):
        new_name = obj.fget.__name__

        def getter(self):
            warn(obj_type='Property')
            return obj.fget(self)

        def setter(self, value):
            warn(obj_type='Property')
            obj.fset(self, value)

        def deleter(self):
            warn(obj_type='Property')
            obj.fdel(self)

        return property(getter, setter, deleter)

    # -------------------------------------------------------- #
    elif inspect.isfunction(obj):
        new_name = obj.__name__

        def wrapper(*args, **kwargs):
            warn(obj_type='Function')
            return obj(*args, **kwargs)

        return wrapper

    # -------------------------------------------------------- #
    elif inspect.isclass(obj):
        new_name = obj.__name__

        class Wrapper(obj):
            def __init__(self, *args, **kwargs):
                warn(obj_type='Class')
                super().__init__(*args, **kwargs)

        return Wrapper

    # -------------------------------------------------------- #
    else:
        raise TypeError(
            'The deprecated object must either be '
            'a property, a function or a class!'
        )
