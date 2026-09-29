# Serialization boundary convention

The JSON provider should convert only values with a defined, intentional JSON representation. For values outside that set, preserve the provider's explicit unsupported-value error; do not infer a representation from incidental structure or silently stringify arbitrary objects. Any conversion must leave the JSON encoder with a value it can safely encode.
