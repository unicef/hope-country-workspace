.PHONY: docs

help:
	@echo help

reset_db:
	dropdb --if-exists country_workspace
	createdb country_workspace
	./manage.py makemigrations
	./manage.py upgrade
	./manage.py sync
	./manage.py demo


clean:
	rm -fr dist coverage.xml db.sqlite3 .coverage ./~build build
	find . -name __pycache__ | xargs rm -fr
	find . -name *.min.min.js | xargs rm

lint:
	pre-commit run --all-files


docs:
	./manage.py env -f "{key} \
\\n   \n{value}\n\n{help}" > ./docs/src/settings.md
	#mkdocs serve

commit-all:
	cd /Users/sax/Documents/data/PROGETTI/UNICEF/hope-flex-fields && git commit -m "updates" && git push
	cd /Users/sax/Documents/data/PROGETTI/UNICEF/hope-smart-export && git commit -m "updates" && git push
	cd /Users/sax/Documents/data/PROGETTI/UNICEF/hope-smart-import && git commit -m "updates" && git push


i18n:  ## i18n support
# get and sync weblate
	git checkout weblate
	git pull
	git checkout develop
	git merge weblate
# process po
	cd src && django-admin makemessages --all --settings=sos.config.settings -d djangojs --pythonpath=. --ignore=~*
	cd src && django-admin makemessages --all --settings=sos.config.settings --pythonpath=. --ignore=~*
	cd src && django-admin compilemessages --settings=sos.config.settings --pythonpath=. --ignore=~*
	git add src/sos/LOCALE
	git commit -am "Update translations"
	git push
# add changes to weblate
	git checkout weblate
	git merge develop
	git push
	git checkout develop
