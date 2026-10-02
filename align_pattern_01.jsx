/*
  Original by Toshiyuki Takahashi https://github.com/gau/reset-pattern
  Modified by Erhan Lale / https://github.com/erhanlale (2026)
  Released under the MIT License.
*/

(function() {

	var SCRIPT_TITLE = 'Align Pattern';
	var SCRIPT_VERSION = '0.1';

	// Settings
	// fitPosition = index into POSITIONS below (0-8)
	var settings = {
		'resetFill' : true,
		'fitPosition' : 0,
	};

	// The 3 x 3 grid, listed row by row, left to right.
	// x: 0 = left,  0.5 = center, 1 = right
	// y: 0 = top,   0.5 = middle, 1 = bottom
	var POSITIONS = [
		// First row
		{ label: 'Top Left',      x: 0,   y: 0   },
		{ label: 'Top Center',    x: 0.5, y: 0   },
		{ label: 'Top Right',     x: 1,   y: 0   },
		// Second row
		{ label: 'Mid Left',      x: 0,   y: 0.5 },
		{ label: 'Mid Center',    x: 0.5, y: 0.5 },
		{ label: 'Mid Right',     x: 1,   y: 0.5 },
		// Third row
		{ label: 'Bottom Left',   x: 0,   y: 1   },
		{ label: 'Bottom Center', x: 0.5, y: 1   },
		{ label: 'Bottom Right',  x: 1,   y: 1   }
	];

	var doc = app.activeDocument;
	var errorFlag = false;
	var targetItems = getTargetItems(doc.selection);

	// UI Dialog
	function mainDialog() {
		this.init();
		return this;
	};
	mainDialog.prototype.init = function() {

		var unit = 20;
		var thisObj = this;

		thisObj.dlg = new Window('dialog', SCRIPT_TITLE + ' - ver.' + SCRIPT_VERSION);
		thisObj.dlg.margins = [unit * 1.5, unit * 1.5, unit * 1.5, unit * 1.5];

		thisObj.positionPanel = thisObj.dlg.add('panel', undefined, 'Position:');
		thisObj.positionPanel.alignment = 'center';
		thisObj.positionPanel.orientation = 'column';
		thisObj.positionPanel.alignChildren = 'center';
		thisObj.positionPanel.margins = [unit, unit, unit, unit];
		thisObj.positionPanel.spacing = unit / 2;

		thisObj.buttonGroup = thisObj.dlg.add('group', undefined);
		thisObj.buttonGroup.margins = [unit, unit, unit, 0];
		thisObj.buttonGroup.alignment = 'center';
		thisObj.buttonGroup.orientation = 'row';

		// Build the grid: one group per row, three radio buttons per group
		thisObj.radioButtons = [];
		var rowGroup = null;
		for (var i = 0; i < POSITIONS.length; i++) {
			if (i % 3 === 0) {
				rowGroup = thisObj.positionPanel.add('group', undefined);
				rowGroup.orientation = 'row';
				rowGroup.spacing = unit * 1.5;
			}
			var radioButton = rowGroup.add('radiobutton', undefined, '');
			radioButton.preferredSize = [unit, unit];
			radioButton.helpTip = POSITIONS[i].label;
			radioButton.onClick = makeClickHandler(i);
			thisObj.radioButtons.push(radioButton);
		}

		// Each button sits in its own row group, so exclusivity is handled manually.
		// The index is captured in a closure so every button knows its own position.
		function makeClickHandler(index) {
			return function() {
				thisObj.selectPosition(index);
				thisObj.updatePreview();
			};
		}

		if (isNaN(settings.fitPosition) || settings.fitPosition < 0 || settings.fitPosition > POSITIONS.length - 1) {
			settings.fitPosition = 0;
		} else {
			settings.fitPosition = Math.floor(settings.fitPosition);
		}
		thisObj.selectPosition(settings.fitPosition);

		thisObj.cancel = thisObj.buttonGroup.add('button', undefined, 'Cancel', {name: 'cancel'});
		thisObj.ok = thisObj.buttonGroup.add('button', undefined, 'Run', { name:'ok'});

		thisObj.ok.onClick = function() {
			app.redo();
			thisObj.closeDialog();
		}
		thisObj.cancel.onClick = function() {
			thisObj.closeDialog();
		}
	};
	mainDialog.prototype.selectPosition = function(index) {
		for (var i = 0; i < this.radioButtons.length; i++) {
			this.radioButtons[i].value = (i === index);
		}
		settings.fitPosition = index;
	};
	mainDialog.prototype.showDialog = function() {
		this.updatePreview();
		this.dlg.show();
	};
	mainDialog.prototype.closeDialog = function() {
		this.dlg.close();
	};
	mainDialog.prototype.updatePreview = function() {
		try {
			originReset();
			app.redraw();
			app.undo();
		} catch(e) {
			alert('Error:' + e);
		}
	};

	// Validation & Show dialog
	var dialog = new mainDialog();
	if (errorFlag && !confirm('Some elements cannot be edited. Continue? \n・Text \n・Symbols \n・Compound shapes')) return false;
	if (!targetItems || targetItems.length < 1) {
		alert('Select an object with a pattern fill!');
	} else {
		dialog.showDialog();
	}

	// Main Process
	function originReset() {

		// for undo
		var dummy = doc.pathItems.add();
		dummy.remove();

		for (var i = 0; i < targetItems.length; i++) {
			var bounds = targetItems[i].geometricBounds;
			var parent = targetItems[i].parent;
			if (parent.typename == 'GroupItem' || parent.typename == 'CompoundPathItem') {
				while (parent.parent.typename == 'GroupItem' || parent.parent.typename == 'CompoundPathItem') {
					parent = parent.parent;
				}
				bounds = parent.geometricBounds;
			}

			// Fill Color Reset
			if (targetItems[i].fillColor.typename == 'PatternColor' && settings.resetFill) {
				var fillColorMatrix = resetMatrix(targetItems[i].fillColor.matrix);
				targetItems[i].fillColor.matrix = setTranslateMatrix(fillColorMatrix, bounds);
			}
		}

	}

	// Get Target Items
	function getTargetItems(items) {
		var targetItems = [];
		for (var i = 0; i < items.length; i++) {
			if (items[i].typename == 'TextRange' || items[i].typename == 'SymbolItem' || items[i].typename == 'PluginItem') {
				errorFlag = true;
			} else {
				if (items[i].typename == 'PathItem') {
					targetItems.push(items[i]);
				} else if(items[i].typename == 'GroupItem') {
					targetItems = targetItems.concat(getTargetItems(items[i].pageItems));
				} else if(items[i].typename == 'CompoundPathItem') {
					targetItems = targetItems.concat(getTargetItems(items[i].pathItems));
				} else if(items[i].typename == 'TextFrame') {
					targetItems = targetItems.concat(getTargetItems(items[i].textRanges));
				}
			}
		}
		return targetItems;
	}

	// Reset Matrix
	function resetMatrix(mtr) {
		mtr.mValueA = 1;
		mtr.mValueB = 0;
		mtr.mValueC = 0;
		mtr.mValueD = 1;
		mtr.mValueTX = 0;
		mtr.mValueTY = 0;
		return mtr;
	}

	// Set Origin Position
	// geometricBounds = [left, top, right, bottom]
	function setTranslateMatrix(mtr, bounds) {
		var left = bounds[0],
			top = bounds[1],
			right = bounds[2],
			bottom = bounds[3];

		var pos = POSITIONS[settings.fitPosition] || POSITIONS[0];

		mtr.mValueTX = left + (right - left) * pos.x;
		mtr.mValueTY = -(top + (bottom - top) * pos.y);
		return mtr;
	}

}());
