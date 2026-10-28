# One injectable system interface

Everything the core needs from the machine (process execution with timeout, PATH and environment, executable resolution, file existence, directory listing) goes through one interface. The real implementation sits behind a platform boundary, which keeps a Linux port cheap, and tests swap in a fake built from captured fixtures so the whole core is tested through the CLI.
