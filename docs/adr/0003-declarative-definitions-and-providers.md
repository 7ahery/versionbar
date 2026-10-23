# Declarative tool definitions, Python providers for managers

Simple tools are TOML definitions the generic engine handles, so adding one needs no engine code and users can add their own in config. Version managers need real logic, so each is a Provider class declaring the tools and OSes it supports. A pure-code model was rejected because it makes contributions heavy; a pure-declarative model was rejected because it cannot express manager layouts.
