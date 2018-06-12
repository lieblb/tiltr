/*
 Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
 GPLv3, see LICENSE
*/

$(function() {
	var port = "11150";
	var host = "http://" + window.location.hostname + ":" + port;

	var workaroundKeys = [];

	$.getJSON(host + "/workarounds.json", function(workarounds) {
		for (var i = 0; i < workarounds.length; i++) {
			var key = workarounds[i][0];
			workaroundKeys.push(key);
			var help = workarounds[i][1];
			$("#workarounds-accordion-content").append('<label class="checkbox"><input id="' +
				key + '" type="checkbox"> ' + key.split("_").join(" ") + '</label><p id="' + key + '_help" class="help"></p>');
			$("#" + key + "_help").text(help);
		}
	});

	function getIcon(name) {
		return $($("#icon_" + name).html());
	}

	function updateResults() {
		$.getJSON(host + "/results.json", function(results) {
			$("#results-overview").empty();
			$("#results").empty();

			if (results.entries.length == 0) {
				$("#results-accordions").hide();
			} else {
				$("#results-accordions").show();
			}

			for (var status in results.counts) {
				var count = results.counts[status];

				var tr = $("<tr></tr>");

				var td;

				td = $("<td></td>");
				td.html(getIcon("status_" + status));
				tr.append(td);

				td = $("<td></td>");
				td.text(count.runs);
				tr.append(td);

				td = $("<td></td>");
				td.text(count.users);
				tr.append(td);

				$("#results-overview").append(tr);
            }

			var entries = results.entries;
			for (var i = 0; i < entries.length; i++) {
				var tr = $("<tr></tr>");
				tr.append($("<td>" + entries[i].time + "</td>"));

				var td = $("<td></td>");
				td.append(getIcon("status_" + entries[i].success));
				tr.append(td);

				tr.append($("<td>" + entries[i].success + ".</td>"));

				tr.append($('<td><a href="' + host + '/result/' + entries[i].batch + '.zip">Download</a></td>'));

				$("#results").append(tr);
			}

			if (entries.length > 0) {
				$.getJSON(host + "/performance.json", function(performance) {
					var trace = {
					    x: performance,
					    type: 'histogram'
					};
					var layout = {
					};
					var data = [trace];
					Plotly.newPlot('performance-plot', data, layout);
				});
			}
		});
	}

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
			var tile = document.createElement("div");
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

			img = document.createElement("img");
			$(img).attr("id", "screen_" + machine);
			$(img).attr("style", "width: 85%; padding-bottom: 0.5em;");

			$(body).append(img);
		}

		$(img).attr("src", src);
	}

	var screenshots = {
		updating: false,
		dirty: {},
		machines: []
	};

	setInterval(function() {
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
		});
	}, 1000);

	function report(machine, message) {
		$("#log").append("[" + machine + "] " + message + "\n");

		var log = $("#log");
		log.scrollTop(log[0].scrollHeight - log.height());

		if (!screenshots.dirty[machine]) {
			screenshots.dirty[machine] = true;
			screenshots.machines.push(machine);
		}
	}

	var restart;
	var connect;
	var connected = false;

	connect = function(batchId) {
		$("#workarounds-accordion").addClass("disabled");
		$("#status-accordion").addClass("is-active");

		$("#start").attr("disabled", true);
		$("#start").addClass("is-loading");
		$("#log").text("");

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

				$("#status-accordion").removeClass("is-active");
				$("#workarounds-accordion").removeClass("disabled");

				/*if ($("#run-loop").hasClass("is-selected")) {
					setTimeout(restart, 1000);
				}*/

				connected = false;
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

	function updateLoopButton() {
		$.getJSON(host + "/settings.json", function(settings) {
			if (settings.looping) {
				$("#run-loop").addClass("is-info is-selected");
			} else {
				$("#run-loop").removeClass("is-info is-selected");
			}
		});
	}
	updateLoopButton();

	$("#run-loop").click(function() {
			$.ajax({
				method: "POST",
				url: host + "/settings.json",
				data: JSON.stringify({
					looping: !$("#run-loop").hasClass("is-selected")})
			}).done(function() {
				updateLoopButton();
			});
	});

	restart = function() {
		if (!$("#start").attr("disabled")) {

			var workarounds = {};
			for (var i = 0; i < workaroundKeys.length; i++) {
				var key = workaroundKeys[i];
				workarounds[key] = $("#" + key).checked;
			}

			$.ajax({
				method: "POST",
				url: host + "/start",
				data: JSON.stringify(workarounds)
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
		updateLoopButton();
	}, 2000);

	$("#start").on("click", restart);

	setScreenshot("master", "/static/default/screen.svg");
	for (var i = 1; i <= NUM_MACHINES; i++) {
		setScreenshot("machine_" + i.toString(), "/static/default/screen.svg");
	}
});