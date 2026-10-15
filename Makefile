# Das Projekt liegt in track_2b/ (Vorgabe Hack Apertus). Diese Datei leitet nur weiter,
# damit `make run` auch hier im obersten Ordner funktioniert.
run demo build check eval app:
	$(MAKE) -C track_2b $@
