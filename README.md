
# <img src="https://github.com/lieblb/tiltr/blob/master/docs/tiltr.png?raw=true" width="200">

TiltR (**T**esting toolkit for the **IL**IAS **T**est & Assessment module **R**egensburg) is a generation-based, smart, black-box fuzzer for the Test & Assessment module of ILIAS 5.

TiltR imports and analyzes a given test and then performs random test runs with a configurable number of automatic robot participants in parallel.

TiltR tests run against well-defined browser environments based on Selenium docker images (you can choose from Chrome and Firefox).

## Scope of Verifications

Using its built-in test oracle TiltR can help institutions that rely on ILIAS for performing e-assessments
assert that some of the most essential functionality they fundamentally rely on for their workflows is correct.

TiltR verifications operate on the following areas:

|                      | Responses         | Response Scores | Total Scores         | Marks        |
| ---------------------|:-----------------:| ---------------:| --------------------:| ------------:|
| **During Test**      |                   |                 |                      |
|                      | &#x2713;          | -               | -                    | -
| **After Test**       |                   |                 |                      |
| via Web UI           | -                 | -               | &#x2713;             | &#x2713;
| via XLS Export       | &#x2713;          | &#x2713;        | &#x2713;             | &#x2713;
| via PDF Export       | -                 | &#x2713;        | -                    | -
| **Readjusted Test**  |                   |                 |                      |
| via XLS Export       | -                 | &#x2713;        | &#x2713;             | &#x2713;
| **Re-Import**        |                   |                 |                      |
| via XLS Export       | &#x2713;          | &#x2713;        | &#x2713;             | &#x2713;

Note that TiltR can not achieve anything like full coverage (even in areas that are marked above).

## Question Types

The following question types are supported:

|                      | Response Verification  | Score Verification  | With Readjustments   |
| ---------------------|:----------------------:| -------------------:| --------------------:|
| Single Choice        |  &#x2713;              |  &#x2713;           | &#x2713;             |
| Multiple Choice      |  &#x2713;              |  &#x2713;           | &#x2713;             |
| KPrim                |  &#x2713;              |  &#x2713;           | &#x2713; (2)         |
| Cloze Select Gaps    |  &#x2713;              |  &#x2713;           | &#x2713;             |
| Cloze Text Gaps      |  &#x2713;              |  &#x2713;           | &#x2713;             |
| Cloze Numeric Gaps   |  &#x2713;              |  &#x2713;           | &#x2713;             |
| Long Text            |  &#x2713;              |  &#x2713;           | &#x2713; (1)         |
| Matching             |  &#x2713;              |  &#x2713;           | &#x2713; (3)         |
| [Paint Question](https://github.com/kyro46/assPaintQuestion)          |  &#x2713;              |  &#x2713;           | -                    |
| [Code Question](https://github.com/frankbauer/ilias-asscodequestion)  | &#x2713;              |  &#x2713;           | -                    |

Notes:

1. only basic support (only simple score, no keyword scores)
2. fully supported, but currently disabled by default due to https://mantis.ilias.de/view.php?id=25105
3. fully supported, but currently disabled by default due to https://mantis.ilias.de/view.php?id=25136

Explanation of Terms:

* Response Verification: are automatically generated answers saved/exported/reimported correctly?
* Score Verification: are scores computed for a specific answer correct?
* With Readjustments: are scores recomputed after readjustments correct?

# Getting Started

TiltR can be run on your local machine or on a server. The first option is fine for trying things out, for longer testing you'll want the second option though. You need to have <a href="https://www.docker.com/community-edition">docker-compose</a> and <a href="https://www.python.org/">python 2 or 3</a> installed.

## First Installation

```
git clone https://github.com/lieblb/tiltr
cd tiltr
docker-compose build
```

The last step can take up to 30 minutes on first install.

You then need to download the source code of ILIAS you want to test against and move it to `tiltr/web/ILIAS`, e.g.:

```
cd /path/to/tiltr
wget https://github.com/ILIAS-eLearning/ILIAS/archive/v5.3.5.tar.gz
tar xzfv v5.3.5.tar.gz
mv ILIAS-5.3.5 web/ILIAS
```

TiltR will instrument your ILIAS code on the first run and automatically build a fully functional installation (you will not need to perform a setup).

## Starting up TiltR

Starting up TiltR happens via the `compose.py` script, which takes the number of parallel client machines you want to start:

```
cd /path/to/tiltr
./compose.py up 5
```

After TiltR started up, you should be able to access the TiltR main GUI under:

`http://mymachine:11150/`

Please note that the default network setup globally exposes your port; if your firewall does not block it, other people will be able to reach your TiltR installation from outside (you can change this by changing TiltR' `docker-compose.yml`).

Be patient during the first setup, it may take some time. If your installation is local, `mymachine` will be `localhost`.

To stop TiltR kill its process. You can also call `./compose.py stop` to shut down any running docker instances.

# The TiltR UI

<img src="https://github.com/lieblb/tiltr/blob/master/docs/main-ui.jpg?raw=true">

## Test Runs

Start an automatic test run via the "Start" button. "Loop" allows to to run test runs indefinitely (i.e. start a new run as soon as one ends).

You can choose which browser to run against in the leftmost popup, which shows "Chrome" by default.

After launching, you will give you basic information and screenshots to see what's happening in its different machines:

<img src="https://github.com/lieblb/tiltr/blob/master/docs/status-ui.jpg?raw=true">

Note: TiltR's virtual participants (called "machines") act in a random manner. A portion of tests can be specified to run in a deterministic manner though,
which is suitable for regression tests (use the `num_deterministic_machines` setting to define the number of such machines).

## Results

The results table gives you detailed protocols of each test run as well as the exported XLS. You can download this data
as a zip file for each completed test run.

Note that all this data gets deleted permanently as soon as you hit the Delete button in the UI.

To get an idea what data is generated for a test run, look at <a href="docs/sample-protocol.zip">a sample protocol and the accompanying XLS export file</a>.

## ILIAS instance

If you want to directly access the ILIAS instance TiltR is testing against, just click on the ILIAS link below the
header. If you're running on the embedded ILIAS, you can login as root using the password "odysseus".

## Workarounds

TiltR will work around a number of known problems in order to perform tests that focus on new, yet unknown issues.

The green boxes in the main UI represent known issues with ILIAS's current behaviour. Turning off one of these boxes will
mean that TiltR will report these issues sooner or later in some test run. Turning boxes on means: "I know about these
issues, please work around them and don't report them". All workaround boxes are on by default.

## Response Times

While running, TiltR gathers response times (in seconds) the various machines experience with the configured ILIAS
installation (i.e. durations of each web request). You can use this as a performance benchmark of how well suited
your ILIAS instance is to deal with a given number of parallel users.

<img src="https://github.com/lieblb/tiltr/blob/master/docs/response-times-ui.jpg?raw=true">

## Error Classes

If TiltR detects an error, it will annotate it with one of the following classes. Here's a 
description of what each class means. The only class you really should be concerned about is
`integrity`. All other classes usually do not indicate structural bugs in ILIAS.

* `not_implemented`
TiltR ran into something that hasn't been implemented yet in TiltR itself,
e.g. some question type that cannot yet be tested. Does not indicate a problem in ILIAS.

* `interaction`
Some problem with Selenium and browser control. This usually comes down to some kind of
timeout problem related to high server load.
Sometimes errors that should belong in `unexpected` get classified as `interaction`
(e.g. the repeated failure to find a button a specific page).

* `unexpected`
ILIAS did something completely unexpected or landed on the error page. You
usually will have to look into ILIAS's error logs to see what happened exactly.
This happens, for example, on failed database transactions.
This class only encompasses explicit problems that should be obvious to the user
as they disrupt the test interaction. This class is mainly a problem if it happens
often, as it implies a test restart with extra time.

* `auto_save`
An integrity error happened, but it happened directly after an autosave and a crash was
triggered, which indicates that the autosave simply didn't run in the specified time frame.
Sporadical errors of this kind do not indicate a structural bug in ILIAS but simply mean
that you have too much load on your server.

* `invalid_save`
A save succeeded even though it shouldn't have. This happens if form verification fails.
For example, entering a string in a numeric cloze should present an error and not continue
to the next question.

* `integrity`
This indicates a bug in ILIAS. Some data was not retrieved in the same state as it was saved.

## TiltR in Action

Here's a short demo:

<img src="https://github.com/lieblb/tiltr/blob/master/docs/sample-video.gif?raw=true">

# Advanced Topics

## Using your own Tests

Running against your own tests is easy. Just export your test as a zip file, then put it into TiltR's
`tests` directory. Reload TiltR's UI and you will see your test listed in the tests dropdown.
Select it and start your test run.

Note that your Tests must have different titles in order to differentiate them in TiltR.

## Using your own ILIAS instance

By default, TiltR runs against its own embedded ILIAS instance (inside Docker). However, you can test
against an existing external ILIAS instance.

**WARNING** Do **not** run TiltR against production instances of ILIAS. TiltR will bulk delete users and tests and
things might go wrong, you know. Instead, to test your infrastructure, create a separate empty instance on your production server that's
only for TiltR testing.

To run TiltR against an external instance, use:

```
./compose.py up [number of machines] --ilias my_ilias.yaml
```

`my_ilias.yaml` contains the relevant information about your ILIAS instance. It should look like this:

```
url: https://some.ilias.uni-regensburg.de
admin:
  user: my_root_user
  password: my_sikrit_root_user_password

```

## Debugging startup problems

Commands like `docker ps` and `docker logs tiltr_master_1` are your friend.

If your tests are fine at the beginning, but the machine gets slower or your machine hangs after a while, it's probably
a problem with chrome. Use `docker stats` and look inside the containers for zombie `chrome` instances. If this is the
case, there's no easy fix.

## Recreating the docker-compose configuration

Strange things happen with docker sometimes and you want to completely recreate the complete docker-compose setup. Here's one way to do this (note that this deletes all dangling volumes of all docker containers, so be very careful if you're not a dedicated machine):

```
cd /path/to/tiltr
docker-compose rm
sudo docker volume rm $(sudo docker volume ls -qf dangling=true)
docker-compose build --no-cache
```

## Cleaning up docker

Over time, and if running over several days, the involved docker images will grow larger and larger (GBs per machine). At some point,
drives might get full and ILIAS will fail with random errors. To clean up, you might want to do a `docker system prune`.

## Building the DB container from scratch

Sometimes - after purging containers - ILIAS itself won't start up and you get `An undefined Database Exception occured. SQLSTATE[42S02]: Base table or view not found`.

In these cases, delete the DB container and image, e.g.:

```
docker rm tiltr_db_1
docker rmi tiltr_db
```

Then start `up.py` and give it several minutes, as the DB import needs substantial time.

## Updating the DB dump for newer versions of ILIAS

TiltR intializes its ILIAS installation using a minimal default DB. As new ILIAS versions are published, it will be necessary to recreate this dump. Here's how to do this:

* Apply hotfixes from new ILIAS version in the TiltR ILIAS installation.

* Then re-export the dump:

```
docker exec -it tiltr_db_1 /bin/bash

root# mysqldump ilias -p > dump.sql
Enter password: dev
root# exit

docker cp tiltr_db_1:/dump.sql /your/local/machine/tiltr/docker/db/ilias.sql
```

Now zip `ilias.sql` and update in your version control.

## More tricks with the embedded ILIAS instance

For the embedded ILIAS instance, you can access setup.php via `http://your.server:11145/ILIAS/setup/setup.php`. The master password is `dev`.

To access the embedded ILIAS' database use Docker:

```
docker exec -it tiltr_db_1 /bin/bash
mysql -u dev -p dev

mysql> use ilias;
```

## Running TiltR with systemd

Very experimental.

Adapt [tiltr.service](./docs/tiltr.service) to your environment and copy it to `/etc/systemd/system/tiltr.service`.

Make sure you change `YOUR_USER_WITH_DOCKER_PRIVILEGES` and `/path/to/tiltr`.

Now you should be able to run these commands:

```
systemctl start tiltr
systemctl stop tiltr
journalctl -u tiltr.service
```

## Notes on the implementation

The "master" container (see `docker-compose.yml`) provides the GUI for running tests and
evaluating test runs; the frontend is just one big Javascript hack, which is not great.

The "web" and "db" container are the ILIAS web server and the ILIAS database.

Each test client runs in a dedicated Docker container, though all browser sessions are
managed centrally in one Selenium container (see "machine" in `docker-compose.yml`).

An alternative for similar projects would be running
Chrome through CEF and https://github.com/cztomczak/cefpython.

## First Setup

...can still be cumbersome. Here are some known problems:

* first launch takes very long (look at db table count on landing page)
* sometimes you need to stop and restart all containers
* sometimes there are random timeouts on user creation
