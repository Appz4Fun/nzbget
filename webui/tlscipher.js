/* Rust TLS cipher optimizer dialog; provider credentials never enter this module. */
var TlsCipherDialog = (new function($)
{
	'use strict';
	var initialized = false, pending = false, timer = null, visible = false;
	var job = '', snapshot = null, appliedJob = '', state = null;
	function text(key, fallback) { return I18n.defaultValue('tls_cipher_' + key, fallback); }
	function active(result) { return ['measuring', 'probing', 'saving'].indexOf(result.State) !== -1; }
	function stopTimer() { if (timer !== null) clearTimeout(timer); timer = null; }
	function message(value) { $('#TlsCipherState').text(value); }
	function failure(value, result)
	{
		pending = false; stopTimer();
		message(result && result.error ? result.error.message : String(value));
		$('#TlsCipherCancel').prop('disabled', true);
	}
	function call(method, params, done)
	{
		RPC.call(method, params, done, failure, { timeout: 15000 });
	}
	function speed(value)
	{
		return typeof value === 'number' && isFinite(value) && value > 0 ?
			(value / 1000000).toFixed(1) + ' MB/s' : text('unmeasured', 'Unmeasured');
	}
	function cell(row, value) { $('<td>').text(value || '').appendTo(row); }
	function render(result)
	{
		state = result; job = result.JobID || '';
		message(result.Message || text(result.State, result.State));
		var progress = '';
		if (result.State === 'measuring' && result.CurrentAlgorithm)
			progress = text('testing_algorithm', 'Testing algorithm') + ': ' + result.CurrentAlgorithm;
		else if (result.State === 'probing')
			progress = (result.CompletedProbes || 0) + ' / ' + (result.TotalProbes || 0) + ' — ' +
				text('server', 'Server') + ' ' + (result.CurrentServer || '') + ': ' + (result.CurrentCipher || '');
		$('#TlsCipherProgress').text(progress).toggle(progress !== '');
		$('#TlsCipherExcluded').toggle((result.ExcludedSuites || []).length > 0)
			.find('p').text((result.ExcludedSuites || []).join(', '));
		$('#TlsCipherCancel').prop('disabled', !active(result));
		$('#TlsCipherAgain').toggle(!active(result) && result.Available !== false && result.State !== 'idle');
		$('#TlsCipherReload').text(text('reload', 'Cipher settings are saved. Reload NZBGet to use them for new connections.'))
			.toggle(result.Saved === true && result.ReloadRequired === true);
		var algorithms = $('#TlsCipherAlgorithms tbody').empty();
		(result.Algorithms || []).forEach(function(item) {
			var row = $('<tr>').appendTo(algorithms);
			cell(row, item.Algorithm); cell(row, speed(item.BytesPerSecond));
			cell(row, item.Minimum && item.Maximum ? speed(item.Minimum) + ' – ' + speed(item.Maximum) : item.Message);
		});
		var servers = $('#TlsCipherServers tbody').empty();
		(result.Servers || []).forEach(function(item) {
			var row = $('<tr>').appendTo(servers);
			cell(row, item.Name || 'Server ' + item.ID);
			cell(row, item.OldCipher || text('default', 'System default'));
			cell(row, item.SelectedCipher || '—');
			cell(row, item.Message || text(item.Outcome, item.Outcome || ''));
			if (Array.isArray(item.CipherSupport) && Array.isArray(result.CipherSuites))
			{
				var details = $('<details>').appendTo(row.children().last());
				$('<summary>').text(text('compatibility', 'Cipher compatibility')).appendTo(details);
				var list = $('<ul>').appendTo(details);
				result.CipherSuites.forEach(function(cipher, index) {
					var support = item.CipherSupport[index];
					$('<li>').text(cipher + ': ' + (support === true ? text('supported', 'Supported') :
						support === false ? text('unsupported', 'Unsupported') : text('unknown', 'Unknown / untested'))).appendTo(list);
				});
			}
		});
		$('#TlsCipherCommon').text(!Array.isArray(result.CommonSupported) ?
			text('common_unknown', 'Common supported ciphers: not fully established') :
			text('common', 'Common supported ciphers') + ': ' +
			((result.CommonSupported || []).join(', ') || text('none', 'None')));
		if (result.Saved === true && result.State === 'completed' && appliedJob !== job)
		{
			appliedJob = job;
			if (!snapshot || !Config.applyCipherResults(result, snapshot))
				message(text('browser_conflict', 'Settings were saved, but your server editor changed. Refresh Settings to see the saved ciphers; your edits have been retained.'));
		}
		stopTimer();
		if (visible && active(result)) timer = setTimeout(poll, 500);
	}
	function poll()
	{
		stopTimer();
		if (!visible || pending) return;
		pending = true;
		call('tlscipherstatus', job ? [job] : [], function(result) { pending = false; render(result); });
	}
	function start()
	{
		if (pending) return;
		snapshot = Config.cipherSnapshot();
		if (snapshot === null)
		{
			message(text('save_servers', 'Save your server changes before optimizing TLS ciphers.'));
			$('#TlsCipherCancel').prop('disabled', true); return;
		}
		pending = true; appliedJob = '';
		$('#TlsCipherAgain').hide();
		message(text('starting', 'Starting cipher tests…'));
		call('tlscipherstart', [], function(result) { pending = false; render(result); });
	}
	this.init = function()
	{
		if (initialized) return;
		initialized = true;
		$('#TlsCipherDialog').on('hidden', function() { visible = false; stopTimer(); })
			.on('shown', function() { $('#TlsCipherClose').focus(); });
		$('#TlsCipherCancel').on('click', function() {
			if (!job || !state || !active(state) || pending) return;
			pending = true; $('#TlsCipherCancel').prop('disabled', true);
			call('tlsciphercancel', [job], function(result) { pending = false; render(result); });
		});
		$('#TlsCipherAgain').on('click', start);
		$(window).on('beforeunload.tlscipher', stopTimer);
	};
	this.refreshAvailability = function()
	{
		var button = $('#Config_OptimizeTls');
		if (!button.length) return;
		button.prop('disabled', true);
		RPC.call('tlscipherstatus', [], function(result) {
			button.prop('disabled', result.Available !== true).attr('title', result.Available === true ? '' :
				(result.Message || text('unavailable', 'TLS cipher optimization requires a TLS-enabled Rust backend.')));
		}, function() {
			button.prop('disabled', true).attr('title', text('unavailable', 'TLS cipher optimization requires a TLS-enabled Rust backend.'));
		}, { timeout: 15000 });
	};
	this.showModal = function()
	{
		this.init(); visible = true;
		$('#TlsCipherDialog').modal({ backdrop: 'static' });
		if (pending) return;
		if (!snapshot) snapshot = Config.cipherSnapshot();
		pending = true;
		call('tlscipherstatus', [], function(result) {
			pending = false;
			if (result.Available === false)
			{
				render(result);
				message(result.Message || text('unavailable', 'TLS cipher optimization requires a TLS-enabled Rust backend.'));
			}
			else if (result.State === 'idle') start();
			else render(result);
		});
	};
}(jQuery));
