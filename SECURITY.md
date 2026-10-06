# Security policy

whencheap makes one HTTPS GET per provider per half hour to fixed, well-known hosts (api.energy-charts.info, api.awattar.de/.at, api.octopus.energy, api.energidataservice.dk, dashboard.elering.ee). It never executes anything received from the network. `whencheap run` executes only the command you pass on the command line.

Things we would like to hear about privately: a crafted API response or TOU file that crashes or hangs the tool, path handling problems in the cache directory, or anything that could make `run` execute something other than your command.

Report via GitHub's private vulnerability reporting on this repository's Security tab. Acknowledgement within 7 days; only the latest release receives fixes.
