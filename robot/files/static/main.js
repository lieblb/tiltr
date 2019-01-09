/*
 Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
 GPLv3, see LICENSE
*/

$(function() {
	var port = window.location.port;
	var host = "http://" + window.location.hostname + ":" + port;

	var settings = {
		fetchWorkarounds: null,
		fetchSettings: null
	};

	// https://gist.github.com/mjackson/5311256
	function hslToRgb(h, s, l) {
	  var r, g, b;

	  if (s == 0) {
		r = g = b = l; // achromatic
	  } else {
		function hue2rgb(p, q, t) {
		  if (t < 0) t += 1;
		  if (t > 1) t -= 1;
		  if (t < 1/6) return p + (q - p) * 6 * t;
		  if (t < 1/2) return q;
		  if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
		  return p;
		}

		var q = l < 0.5 ? l * (1 + s) : l + s - l * s;
		var p = 2 * l - q;

		r = hue2rgb(p, q, h + 1/3);
		g = hue2rgb(p, q, h);
		b = hue2rgb(p, q, h - 1/3);
	  }

	  return `rgb(${r * 255}, ${g * 255}, ${b * 255})`;
	  //return [ r * 255, g * 255, b * 255 ];
	}

	function createTogglesDashboard(container, items) {
		var isChecked = {};

		function setIsChecked(tile, checked) {
			var enabledClass = 'is-primary';
			$(tile).removeClass('is-light ' + enabledClass);
			$(tile).addClass(checked ? enabledClass : 'is-light');
			var key = $(tile).attr('data-toggle-key');
			isChecked[key] = checked;
		}

		function toggleTile(e) {
			var key = $(this).attr('data-toggle-key');
			setIsChecked(this, !isChecked[key]);
			return false;
		}

		var dashboard = $('<div></div>');
		dashboard.addClass('tile is-ancestor');

		var numRows = Math.ceil(items.length / 3);
		var i = 0;
		while (i < items.length) {
			var column = $('<div></div>');
			column.addClass('tile is-parent is-vertical');

			var j = 0;
			while (i < items.length && j < numRows) {
				var key = items[i][0];
				var title = items[i][1];
				var description = items[i][2];
				var checked = items[i][3];

				var article = $('<article></article>');
				article.addClass('tile is-child box notification');
				article.attr('data-toggle-key', key);
				article.click(toggleTile);
				article.addClass('no-text-selection');

				var text1 = $('<span></span>');
				text1.text(description);
				article.append(text1);
				var text2 = $('<span></span>');
				text2.addClass('is-italic');
				text2.text(' ' + title);
				article.append(text2);

				setIsChecked(article, checked);

				i += 1;
				j += 1;
				column.append(article);
			}

			dashboard.append(column);
		}

		container.append(dashboard);

		return function() {
			return isChecked;
		};
	}

	function createSettingsDashboard(container, items) {
		var ignoredInDashboard = {};
		ignoredInDashboard['browser'] = true;

		items = items.filter(function(item) {
			return ignoredInDashboard[item[0]] !== true;
		});

		var dashboard = $('<div></div>');
		dashboard.addClass('tile is-ancestor');

		var inputs = [];

		var numRows = Math.ceil(items.length / 3);
		var i = 0;
		while (i < items.length) {
			var column = $('<div></div>');
			column.addClass('tile is-parent is-vertical');

			var j = 0;
			while (i < items.length && j < numRows) {
				var key = items[i][0];
				var description = items[i][1];
				var value = items[i][2];

				var article = $('<article></article>');
				article.addClass('tile is-child box notification info');

				var text1 = $('<div></div>');
				text1.text(description);
				article.append(text1);

				article.append($('<hr>'));

				var input = $('<input type="text"></input>');
				input.addClass('input is-size-7');
				input.attr('id', 'setting-' + key);
				inputs.push([key, input.attr('id')]);
				input.val(value);
				article.append(input);

				i += 1;
				j += 1;
				column.append(article);
			}

			dashboard.append(column);
		}

		container.append(dashboard);

		return function() {
			var settings = {};
			for (var i = 0; i < inputs.length; i++) {
				settings[inputs[i][0]] = $('#' + inputs[i][1]).val();
			}

			settings['browser'] = $('#select-browser').val();

			return settings;
		};
	}

	$.getJSON(host + "/preferences.json", function(preferences) {
		settings.fetchWorkarounds = createTogglesDashboard(
			$("#workarounds-dashboard"),
			preferences.workarounds.map(
				function(w) {
					var parts = /^(W[0-9]+) (.+)/g;
					var m = parts.exec(w.description);
					return [w.key, m ? m[1] : '', m ? m[2] : w.description, w.value];
				}
			)
		);

		settings.fetchSettings = createSettingsDashboard(
			$("#settings-dashboard"),
			preferences.settings.map(
				function(s) {
					return [s.key, s.description, s.value];
				}
			));
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

	function updatePanels() {
		if (panels.coverage) {
			$.getJSON(host + "/results-coverage.json", function(coverage) {
				$("#toggle-coverage").removeClass("is-loading");
				$("#message-results-coverage .message-body").show();
				updateCoverage(coverage);
	        });
		} else {
			$("#message-results-coverage .message-body").hide();
			$("#toggle-coverage").removeClass("is-loading");
		}

		if (panels.details) {
			$.getJSON(host + "/results-details.json", function(entries) {
				$("#toggle-details").removeClass("is-loading");

				$("#results").empty();

				$("#message-results-details .message-body").show();

				for (var i = 0; i < entries.length; i++) {
					var tr = $("<tr></tr>");
					tr.append($("<td>" + entries[i].time + "</td>"));

					tr.append($("<td>" + entries[i].elapsed + "s</td>"));

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
			$("#toggle-details").removeClass("is-loading");
		}

		if (panels.performance) {
			$("#message-results-performance .message-body").show();

			$.getJSON(host + "/results-performance.json", function(performance) {
				$("#toggle-performance").removeClass("is-loading");
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
			$("#toggle-performance").removeClass("is-loading");
		}

		if (panels.longterm) {
			$("#message-results-longterm .message-body").show();

			$.getJSON(host + "/results-longterm.json", function(longterm) {
				$("#toggle-longterm").removeClass("is-loading");

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
			$("#toggle-longterm").removeClass("is-loading");
            $("#message-results-longterm .message-body").hide();
        }
	}

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

		updatePanels();
	}

	$("#toggle-coverage").on("click", function() {
		$("#toggle-coverage").addClass("is-loading");
		panels.coverage = !panels.coverage;
		updatePanels();
	});

	$("#toggle-details").on("click", function() {
		$("#toggle-details").addClass("is-loading");
		panels.details = !panels.details;
		updatePanels();
	});

	$("#toggle-performance").on("click", function() {
		$("#toggle-performance").addClass("is-loading");
		panels.performance = !panels.performance;
		updatePanels();
	});

	$("#toggle-longterm").on("click", function() {
		$("#toggle-longterm").addClass("is-loading");
		panels.longterm = !panels.longterm;
		updatePanels();
	});

	$("#delete-results").click(function() {
		$("#delete-results").addClass("is-loading");
		$.ajax({
			url: host + "/delete-results",
		}).done(function(data) {
			$("#delete-results").removeClass("is-loading");
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

		var machineNo = machine.match(/\d+/g);
		if (machineNo == null) {
			machineNo = 0;
		} else {
			machineNo = Number(machineNo[0]);
		}
		tag.css("background-color", hslToRgb(machineNo / 20, 0.5, 0.75));

		tag.css("color", "black");
		tag.text(machine);

		var entry = $("<div></div>");
		entry.append(tag);

		var text = $("<span></span>");
		text.text(" " + message);
		entry.append(text);

		var log = $("#log");
		var updateScroll = (
			log.scrollTop() >= log[0].scrollHeight - log.height() - 50);
		log.append(entry);
		if (updateScroll) {
			log.scrollTop(log[0].scrollHeight - log.height());
		}

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

		$("#select-browser").attr("disabled", true);
		$("#select-test").attr("disabled", true);

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

				$("#select-browser").attr("disabled", false);
				$("#select-test").attr("disabled", false);

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
			if (settings.is_looping) {
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
				is_looping: !$("#run-loop").hasClass("is-selected")})
		}).done(function() {
			updateSettings();
		});
	});

	restart = function() {
		if (!$("#start").attr("disabled")) {

			$.ajax({
				method: "POST",
				url: host + "/start",
				data: JSON.stringify({
					test: $("#select-test").val(),
					workarounds: settings.fetchWorkarounds(),
					settings: settings.fetchSettings()
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