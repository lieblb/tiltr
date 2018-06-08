; <?php exit; ?>
[server]
http_path = "http://localhost:8081"
absolute_path = "/var/www/html/ILIAS"
presetting = ""
timezone = "Europe/Berlin"

[clients]
path = "data"
inifile = "client.ini.php"
datadir = "/var/ilias/data"
default = ""
list = "0"

[setup]
; password "dev"
pass = "e77989ed21758e78331b20e477fc5582"

[tools]
convert = "/usr/bin/convert"
zip = "/usr/bin/zip"
unzip = "/usr/bin/unzip"
java = ""
ffmpeg = ""
ghostscript = "/usr/bin/gs"
latex = ""
vscantype = "none"
scancommand = ""
cleancommand = ""
enable_system_styles_management = ""
lessc = ""
phantomjs = "/usr/bin/phantomjs"
fop = ""

[log]
path = "/var/ilias/log"
file = "ilias.log"
enabled = "1"
level = "WARNING"
error_path = "/var/ilias/log"

[debian]
data_dir = "/var/opt/ilias"
log = "/var/log/ilias/ilias.log"
convert = "/usr/bin/convert"
zip = "/usr/bin/zip"
unzip = "/usr/bin/unzip"
java = ""
ffmpeg = "/usr/bin/ffmpeg"

[redhat]
data_dir = ""
log = ""
convert = ""
zip = ""
unzip = ""
java = ""

[suse]
data_dir = ""
log = ""
convert = ""
zip = ""
unzip = ""
java = ""

[https]
auto_https_detect_enabled = "0"
auto_https_detect_header_name = ""
auto_https_detect_header_value = ""
