# Typeclasses and monads in stdlib Python 3.10+: what pyright makes of them

Findings from probing candidate designs for `omadotfile` with pyright (`--pythonversion 3.10`,
standard and strict mode). Useful before reaching for a Result/Option type or `singledispatch`.

- **Result/Either as `Ok[T] | Err[E]`**: `bind` keeps error types precise
  (`Ok[dict[str, str]] | Err[KeyError] | Err[ValueError]`) and `match` narrows both sides. But
  `Err.map`/`Err.bind` must accept any callable: `Callable[[object], object]` breaks every
  lambda, `Any` leaks Any, and `typing.Never` does not exist on 3.10 (`typing_extensions` is
  not stdlib). With `NoReturn` it passes standard mode, but in strict mode lambdas in `.map(...)`
  chains come out partially `Unknown` (they are also checked against the `Err` branch), and
  `Ok({})` inside a lambda is `dict[Unknown, Unknown]`.
- **Single-class `Result[T, E]`** checks clean in strict mode, but needs internal `cast`s,
  cannot be narrowed with `match`, and a constructor like `success(v)` cannot infer `E`.
- **Tracebacks**: each `.map` link adds a frame plus a `<lambda>` frame, and an exception that
  is built but never raised (`Err(ValueError(...))`) has `__traceback__ is None`, so it does
  not say where it came from. Raising plus a boundary decorator (`warns_on`/`skips`) gives the
  same either-or control flow with real tracebacks.
- **Option**: `T | None` with walrus and narrowing already is Option, fully understood by pyright.
- **Reader**: functions of `ctx` and closures over it (`found_any(...)`, `partial(...)`) already
  are Reader; a monad adds only ceremony.
- **`functools.singledispatch`**: pyright types the result as the base function's return type,
  accepts calls with no registered handler, and leaves `register` arguments unchecked;
  registering `list[str]` raises at runtime on 3.10 ("is not a class").
- **ABC vs Protocol for traits**: `@abstractmethod` makes pyright report
  `Cannot instantiate abstract class` for a subclass missing a method (and Python raises at
  instantiation); a bare `raise NotImplementedError` body is never reported. Neither ABCs nor
  Protocols check that a subclass sets a `ClassVar`.
- **Generic Protocol "typeclass" instances** (e.g. `Codec[T]` with `load`/`dump` staticmethods,
  module-level instances passed explicitly) infer precisely: a missing method is an
  assignment error to `Codec[str]`, and `T` flows into `Callable[[T], T]` transforms.
