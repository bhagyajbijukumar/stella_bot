"""
Copyright (C) by stella or something
if you copy this but make your repository private, ur weird
pls be nice to me if you do copy it that's all i want :pleading:
"""
import contextlib
import discord
import itertools
import inspect
from utils.errors import ConsumerUnableToConvert
from discord.ext import commands
from discord.ext.commands import CommandError, ArgumentParsingError


class WithCommaStringView(commands.view.StringView):
    """Custom StringView for Separator and Consumer class to use."""
    def __init__(self, view):
        super().__init__(view.buffer)
        self.old_view = view

    def update_values(self):
        """Update the current StringView value into this object""" 
        self.__dict__.update({key: getattr(self.old_view, key) for key in ["previous", "index", "end"]})

    def get_parser(self, converter):
        """Tries to get a separator within an argument, return None if it can't find any."""
        if not hasattr(converter, "separators"):
            return
        pos = 0
        escaped = []
        with contextlib.suppress(IndexError):
            while not self.eof:
                current = self.buffer[self.index + pos]
                if current in converter.separators:
                    if previous not in converter.escapes:
                        break
                    else:
                        escaped.append(pos - 1)
                    
                pos += 1
                previous = current
        
        for offset, escape in enumerate(escaped):
            maximum = self.index + escape - offset
            self.buffer = self.buffer[0: maximum] + self.buffer[maximum + 1: self.end]
            self.end -= 1
        pos -= len(escaped)
        if self.index + pos != self.end:
            return pos

    def get_arg_parser(self, end):
        """Gets a word that ends with ','"""
        self.previous = self.index
        offset = 0
        PARSERSIZE = 1
        # Undo if there is a space, to not capture it
        while self.buffer[self.index + end - (1 + offset)].isspace():
            offset += 1
        result = self.buffer[self.index:self.index + (end - offset)]
        self.index += end + PARSERSIZE
        return result


class BaseGreedy(commands.converter._Greedy):
    """A Base class for all Greedy subclass, basic attribute such as separators
       and escapes."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.separators = {','}
        self.escapes = {'\\'}

    def add_into_instance(self, instance, separators, escapes):
        if not hasattr(separators, "__iter__"):
            raise Exception("Separators passed must be an iterable.")
        if not hasattr(escapes, "__iter__"):
            raise Exception("Escapes passed must be an iterable.")
        for s, e in itertools.zip_longest(separators, escapes):
            if s and len(s) != 1:
                raise Exception("Separator must only be a single character.")
            if e and len(e) != 1:
                raise Exception("Escape must only be a single character.")
        instance.separators |= set(separators)
        instance.escapes |= set(escapes)
        return instance

    def __getitem__(self, param):
        new_param = param
        if hasattr(param, "__iter__"):
            new_param = new_param[0]
        instance = super().__getitem__(new_param) 
        if hasattr(param, "__iter__"):
            separators, escapes = param[1:] if len(param) > 2 else (param[1], {})
            instance = self.add_into_instance(instance, separators, escapes)
        return instance

    def __call__(self, *separators, escapes={}):
        instance = self.add_into_instance(self, separators, escapes)
        return instance
    
    async def actual_greedy_parsing(self, command, ctx, param, required, converter):
        raise NotImplemented("Greedy subclass seems to not have this method. It dies.")
    
class _SeparatorParsing(BaseGreedy):
    """Allow Greedy to be parse in a way that it will try to find ',' or any
       other passed separator in an argument, and will allow spaced argument to be
       passed given that there are a separator at the end of each argument.
       
       Returns an empty list when none of the argument was valid."""

    async def actual_greedy_parsing(self, command, ctx, param, required, converter):
        view = ctx.view
        result = []
        while not view.eof:
            previous = view.index
            view.skip_ws()
            try:
                if pos := view.get_parser(param.annotation):
                    argument = view.get_arg_parser(pos)
                else:
                    argument = view.get_quoted_word()
                value = await command.do_conversion(ctx, converter, argument, param)
            except (CommandError, ArgumentParsingError):
                view.index = previous
                break
            else:
                result.append(value)

        if not result and not required:
            return param.default
        return result


class _ConsumerParsing(BaseGreedy):
    """Allow a consume rest behaviour by trying to convert an argument into a valid
       conversion for each word it sees.
       Example: 'uwu argument1 argument2 argument3'

       If the Greedy is at argument1, it will try to first convert "argument1"
       when fails, it goes into "argument1 argument2" and so on.

       This Greedy raises an error if it can't find any valid conversion."""

    async def actual_greedy_parsing(self, command, ctx, param, required, converter):
        view = ctx.view
        view.skip_ws()
        if pos := view.get_parser(param.annotation):
            current = view.get_arg_parser(pos)
            return await command.do_conversion(ctx, converter, current, param)

        previous = view.index
        once = 0
        while not view.eof:
            view.skip_ws()
            with contextlib.suppress(CommandError, ArgumentParsingError):
                if not once:
                    current = view.get_quoted_word()
                else:
                    while not view.eof:
                        if view.buffer[view.index].isspace():
                            break
                        view.index += 1
                    
                    current = view.buffer[previous: view.index]
                once |= 1
                return await command.do_conversion(ctx, converter, current, param)

        name = (converter if inspect.isclass(converter) else type(converter)).__name__
        raise ConsumerUnableToConvert(view.buffer[previous: view.index], name, converter=converter)

Separator = _SeparatorParsing()
Consumer = _ConsumerParsing()


class GreedyParser(commands.Command):
    async def _transform_greedy_pos(self, ctx, param, required, greedy, converter, normal_greedy=False):
        """Allow Greedy subclass to have their own method of conversion by checking "actual_greedy_parsing"
           method, and invoking that method when it is available, else it will call the normal greedy method
           conversion."""

        if hasattr(greedy, "actual_greedy_parsing") and not normal_greedy:
            result = await greedy.actual_greedy_parsing(self, ctx, param, required, converter)
        else:
            result = await super()._transform_greedy_pos(ctx, param, required, converter)
        if hasattr(converter, 'after_greedy'):
            return await converter.after_greedy(ctx, result)
        return result


    async def transform(self, ctx, param):
        """Because Danny literally only allow commands.converter._Greedy class to be pass here using
           'is' comparison, I have to override it to allow any other Greedy subclass.
           
           It's obvious that Danny doesn't want people to subclass it smh."""

        required = param.default is param.empty
        converter = self._get_converter(param)
        if isinstance(converter, commands.converter._Greedy):
            if param.kind == param.POSITIONAL_OR_KEYWORD or param.kind == param.POSITIONAL_ONLY:
                return await self._transform_greedy_pos(ctx, param, required, converter, converter.converter)

        return await super().transform(ctx, param)