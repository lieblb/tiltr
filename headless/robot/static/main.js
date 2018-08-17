/*
 Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
 GPLv3, see LICENSE
*/

$(function() {
	var port = "11150";
	var host = "http://" + window.location.hostname + ":" + port;

	var workaroundKeys = [];
	var settingKeys = [];

	$.getJSON(host + "/preferences.json", function(preferences) {
		var settings = preferences.settings;
		for (var i = 0; i < settings.length; i++) {
			var key = settings[i].key;
			settingKeys.push(key);
			var description = settings[i].description;
			$("#settings-table").append('<tr><td><label><input id="' +
				key + '" type="text" class="input is-rounded is-size-7"></td><td>' + description +
				'</label><p id="' + key + '_help" class="help"></p></td></tr>');
			//$("#" + key + "_help").text(help);
			$("#" + key).val(settings[i].value);
		}

		var workarounds = preferences.workarounds;
		for (var i = 0; i < workarounds.length; i++) {
			var key = workarounds[i].key;
			workaroundKeys.push(key);
			//var help = workarounds[i].description;

			var regex = /^(W[0-9]+) (.+)/g;
			var match = regex.exec(workarounds[i].description);

			$("#workarounds-table").append('<tr><td><label class="checkbox"><input id="' +
				key + '" type="checkbox"> ' + match[1] + '</label><span id="' +
				key + '_help" class="is-pulled-right"></span></td></tr>');
			$("#" + key + "_help").text(match[2]);
			$("#" + key).prop("checked", workarounds[i].value);
		}
	});

	$.getJSON(host + "/tests.json", function(tests) {
		$("#select-test").empty();
		for (var test in tests) {
			var option = $("<option></option>");
			option.attr("value", tests[test]);
			option.text(test);
			$("#select-test").append(option);
		}

	});

	function getIcon(name) {
		var element = $("#icon_" + name.toLowerCase());
		if (element.length == 0) {
			element = $("#icon_status_fail");
		}
		return $(element.html());
	}

	function removeIds(element) {
		$(element).children().each(function() {
			$(this).removeAttr("id");
			removeIds(this);
		});
	}

	function updateCoverage(coverage) {
		if (coverage.cases < 1) {
			$("#message-results-coverage").hide();
			return;
		}

        var percentage = 100.0 * coverage.observed / coverage.cases;
        $("#coverage").val(percentage);
        var coverageText = percentage.toFixed(1) + "%";
        $("#coverage").text(coverageText);

        $("#coverage-cases").text(coverage.cases);
        $("#coverage-observed").text(coverage.observed);
        $("#coverage-percentage").text(coverageText);

        while (true) {
	        var children = $("#coverage-overview").children();
	        if (children.length < 2) {
	        	break;
			}
			$(children[1]).remove();
		}

		var n = coverage.questions.length;
		for (var i = 0; i < n; i++) {
			var q = coverage.questions[i];

			var row = $($("#coverage-row").html());
			$(row).find("#name").text(q.name);

			if (q.cases > 0 && q.observed !== undefined) {
				var percentage = 100.0 * q.observed / q.cases;
				var coverageText = percentage.toFixed(1) + "%";

				$(row).find("#coverage").val(percentage);
				$(row).find("#coverage-cases").text(q.cases);
				$(row).find("#coverage-observed").text(q.observed);
				$(row).find("#coverage-percentage").text(coverageText);
			} else {
				$(row).find("#coverage").val(0);
				$(row).find("#coverage-cases").text("0");
				$(row).find("#coverage-observed").text("0");
				$(row).find("#coverage-percentage").text("0");
			}

			removeIds(row);
			$("#coverage-overview").append(row);
		}
    }

    var panels = {
		"coverage": false,
		"details": false,
		"performance": false,
		"longterm": false
	};

	function updateResults() {
		$.getJSON(host + "/results-counts.json", function(counts) {
            $("#results-overview").empty();

			var n = 0;
			for (var status in counts) {
				var count = counts[status];

				var tr = $("<tr></tr>");

				var td;

				td = $("<td></td>");
				td.html(getIcon("status_" + status.replace("/", "_")));
				tr.append(td);

				td = $("<td></td>");
				td.text(count.runs);
				tr.append(td);

				td = $("<td></td>");
				td.text(count.users);
				tr.append(td);

				$("#results-overview").append(tr);

				n += count.runs;
            }

			var articles = $('article[id^="message-results"]');
			if (n < 1) {
				articles.hide();
			} else {
				articles.show();
			}
			$('article[id="message-results-longterm"]').show();
        });

		if (panels.coverage) {
			$.getJSON(host + "/results-coverage.json", function(coverage) {
				$("#message-results-coverage .message-body").show();
				updateCoverage(coverage);
	        });
		} else {
			$("#message-results-coverage .message-body").hide();
		}

		if (panels.details) {
			$.getJSON(host + "/results-details.json", function(entries) {
				$("#results").empty();

				$("#message-results-details .message-body").show();

				for (var i = 0; i < entries.length; i++) {
					var tr = $("<tr></tr>");
					tr.append($("<td>" + entries[i].time + "</td>"));

					var success = entries[i].success;

					var td = $("<td></td>");
					td.append(getIcon("status_" + success.replace("/", "_")));
					tr.append(td);

					tr.append($("<td>" + success + ".</td>"));

					tr.append($('<td><a href="' + host + '/result/' + entries[i].batch + '.zip">Download</a></td>'));

					$("#results").append(tr);
				}
			});
		} else {
			$("#message-results-details .message-body").hide();
		}

		if (panels.performance) {
			$("#message-results-performance .message-body").show();

			$.getJSON(host + "/results-performance.json", function(performance) {
				var trace = {
					x: performance,
					type: 'histogram'
				};
				var layout = {
				};
				var data = [trace];
				Plotly.newPlot('performance-plot', data, layout);
			});
		} else {
			$("#message-results-performance .message-body").hide();
		}

		if (panels.longterm) {
			$("#message-results-longterm .message-body").show();

			$.getJSON(host + "/results-longterm.json", function(longterm) {
				var counts = {"OK": 0, "FAIL": 0};

				var x = [];
				var y = [];
				var colors = [];

				for (var i = 0; i < longterm.length; i++) {
					var r = longterm[i];
					x.push(r[0]);
					colors.push(r[1] > 0 ? 'rgb(0, 200, 0)' : 'rgb(200, 0, 0)');
					y.push(r[2]);

					counts[r[1] > 0 ? "OK" : "FAIL"] += r[2];
				}

				data = [{
					x: x,
					y: y,
					type: 'bar',
					showlegend: true,
					name: name,
					marker: {
						color: colors
					}
				}];

				var layout = {
				};

				Plotly.newPlot('longterm-plot', data, layout);

				$("#longterm-ok").text(counts["OK"] + " users");
				$("#longterm-fail").text(counts["FAIL"] + " users");
			});
		} else {
            $("#message-results-longterm .message-body").hide();
        }
	}

	$("#toggle-coverage").on("click", function() {
		panels.coverage = !panels.coverage;
		updateResults();
	});

	$("#toggle-details").on("click", function() {
		panels.details = !panels.details;
		updateResults();
	});

	$("#toggle-performance").on("click", function() {
		panels.performance = !panels.performance;
		updateResults();
	});

	$("#toggle-longterm").on("click", function() {
		panels.longterm = !panels.longterm;
		updateResults();
	});

	$("#delete-results").click(function() {
		$.ajax({
			url: host + "/delete-results",
		}).done(function(data) {
			updateResults();
		});
	});

	updateResults();

	function machineIndex(machine) {
		return (machine == "master" ?
			0 :
			parseInt(machine.replace("machine_", "")));
	}

	function setScreenshot(machine, src) {
		var img = $("#screen_" + machine);
		if (img.length == 0) {
			var tile = $("<div></div>");
			$(tile).attr("class", "tile is-4 machine");
			$(tile).attr("style", "padding:1em;");
			$(tile).attr("data-machine-index", machineIndex(machine));

			var row = 1;
			while ($("#imagerow" + row.toString() + " .machine").length == 3) {
				row += 1;
			}

			var imagerow = $("#imagerow"+ row.toString());
			if (imagerow.length == 0) {
				imagerow = $('<div id="imagerow' + row.toString() + '" class="tile is-ancestor"></div>');
				$("#images").append(imagerow);
			}
			$(imagerow).append(tile);

			var article = $('<article class="message"></article>');
			var header = $('<div class="message-header">' + machine + '</div>');
			var body = $('<div class="message-body"></div>');

			$(article).append(header);
			$(article).append(body);

			$(tile).append(article);

            var link = $("<a><img></a>");

			//img = document.createElement("img");
			img = $(link).find("img");
            $(img).attr("id", "screen_" + machine);
			$(img).attr("style", "width: 85%; padding-bottom: 0.5em;");

            $(link).append(img);
			$(body).append(link);

            var hiddenImage = document.createElement("img");
            $(hiddenImage).css({
                "display": "none"
            });
            $(hiddenImage).attr("id","popup_screen_" + machine);
            $(article).append(hiddenImage);

            $(link).attr("data-fancybox", "machines");
            $(link).attr("data-caption", machine);
            $(link).attr("href", "javascript:;");
            $(link).attr("data-src", "#popup_screen_" + machine);
		}

		$(img).attr("src", src);
		$("#popup_screen_" + machine).attr("src", src);
	}

	$().fancybox({
        selector: '[data-fancybox="machines"]',
        loop: false,
        arrows: false,
        keyboard: false
    });

	var screenshots = {
		updating: false,
		dirty: {},
		machines: []
	};

    var connected = false;

    function updateScreenshots() {
		if (screenshots.updating) {
			return;
		}

		if (screenshots.machines.length < 1) {
			return;
		}

		var machine = screenshots.machines.shift();
		screenshots.dirty[machine] = false;

		screenshots.updating = true;
		$.ajax({
			url: host + "/screenshot/" + machine,
		}).done(function(data) {
			if (data) {
				setScreenshot(machine, "data:image/png;base64," + data);
			}
		}).always(function() {
			screenshots.updating = false;
			if (!connected) {
                updateScreenshots();
            }
		});
    }

	setInterval(updateScreenshots, 1000);

	function report(machine, message) {
		var tag = $('<span class="tag is-light"></span>');
		tag.text(machine);

		var entry = $("<div></div>");
		entry.append(tag);

		var text = $("<span></span>");
		text.text(" " + message);
		entry.append(text);

		var log = $("#log");
		log.append(entry);
		log.scrollTop(log[0].scrollHeight - log.height());

		if (!screenshots.dirty[machine]) {
			screenshots.dirty[machine] = true;
			screenshots.machines.push(machine);
		}
	}

	var restart;
	var connect;

	connect = function(batchId) {
		$("#workarounds").addClass("disabled");
		$("#status").addClass("is-active");

		$("#status").show();
		$("#workarounds").hide();

		$("#start").attr("disabled", true);
		$("#start").addClass("is-loading");
		$("#log").empty();

		console.log("connecting to batch " + batchId);
		connected = true;

		var ws = new WebSocket(
			"ws://" + window.location.hostname + ":" + port + "/websocket/" + batchId);

		ws.onmessage = function(evt) {
			var data = JSON.parse(evt.data);

			if (data.command == "report") {
				report(data.origin, data.message);
			} else if (data.command == "done") {
				updateResults();

				$("#start").removeClass("is-loading");
				$("#start").attr("disabled", false);

				ws.onclose = function() {
					// ok to close now.
				};

				ws.close();

				$("#status").removeClass("is-active");
				$("#workarounds").removeClass("disabled");
				$("#workarounds").show();

				if (data.success == "OK") {
					$("#status").hide();
				}


				/*if ($("#run-loop").hasClass("is-selected")) {
					setTimeout(restart, 1000);
				}*/

				connected = false;
			} else {
				console.log("invalid message", data);
			}
		};

		ws.onopen = function() {
		};

		ws.onclose = function() {
			console.log("lost web socket connection. trying to reestablish in 1s.");

			setTimeout(function() {
				connect(batchId);
			}, 1000);
		};
	}

	function updateSettings() {
		$.getJSON(host + "/settings.json", function(settings) {
			if (settings.looping) {
				$("#run-loop").addClass("is-info is-selected");
			} else {
				$("#run-loop").removeClass("is-info is-selected");
			}
			$("#host_disk_free").text(settings.host_disk_free + " on host disk.");
		});
	}
	updateSettings();

	$("#run-loop").click(function() {
		$.ajax({
			method: "POST",
			url: host + "/settings.json",
			data: JSON.stringify({
				looping: !$("#run-loop").hasClass("is-selected")})
		}).done(function() {
			updateSettings();
		});
	});

	restart = function() {
		if (!$("#start").attr("disabled")) {

			var workarounds = {};
			for (var i = 0; i < workaroundKeys.length; i++) {
				var key = workaroundKeys[i];
				workarounds[key] = $("#" + key).prop("checked");
			}

			var settings = {};
			for (var i = 0; i < settingKeys.length; i++) {
				var key = settingKeys[i];
				settings[key] = $("#" + key).val();
			}

			$.ajax({
				method: "POST",
				url: host + "/start",
				data: JSON.stringify({
					test: $("#select-test").val(),
					workarounds: workarounds,
					settings: settings
                })
			}).done(function(batchId) {
				if (batchId == "error") {
					alert("ILIAS is not available. Please try again later.")
				} else {
					connect(batchId);
				}
			});
		}		
	};

	setInterval(function() {
		if (!connected) {
			$.getJSON(host + "/status.json", function(status) {
				if (!connected && status.batchId) {
					connect(status.batchId);
				}
			});
		}
		updateSettings();
	}, 2000);

	$("#start").on("click", restart);
	$("#status").hide();

	setScreenshot("master", "/static/default/screen.svg");
	for (var i = 1; i <= NUM_MACHINES; i++) {
		setScreenshot("machine_" + i.toString(), "/static/default/screen.svg");
	}
});