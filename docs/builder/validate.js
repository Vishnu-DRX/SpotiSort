// Port of src/config.py (parse_config) to JavaScript. Keep in sync with the Python validator:
// same rules, same messages. Returns a list of errors; each error also says which form field it belongs to.
(function (root) {
  'use strict';

  var TOP_LEVEL_KEYS = ['default_days_threshold', 'fallback_playlist', 'rules', 'language_playlists', 'enrichment'];
  var ENRICHMENT_KEYS = ['musicbrainz', 'english_default'];
  var RULE_KEYS = ['name', 'enabled', 'match', 'target_playlist', 'days_threshold', 'create_missing_playlists'];
  var LIST_MATCH_KEYS = ['artist_in', 'genre_contains', 'language_in'];
  var INT_MATCH_KEYS = ['release_year_before', 'release_year_after'];
  var STR_MATCH_KEYS = ['track_name_contains', 'album_name_contains'];
  var BOOL_MATCH_KEYS = ['explicit'];
  var MATCH_KEYS = LIST_MATCH_KEYS.concat(INT_MATCH_KEYS, STR_MATCH_KEYS, BOOL_MATCH_KEYS);

  function has(list, key) { return list.indexOf(key) !== -1; }
  function isInt(v) { return typeof v === 'number' && isFinite(v) && Math.floor(v) === v; }
  function nonemptyStr(v) { return typeof v === 'string' && v.trim() !== ''; }
  function isMap(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

  // Python repr() of a str, as used in the '!r' messages.
  function pyRepr(s) {
    s = String(s);
    var q = s.indexOf("'") !== -1 && s.indexOf('"') === -1 ? '"' : "'";
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var c = s[i];
      if (c === '\\') out += '\\\\';
      else if (c === q) out += '\\' + q;
      else if (c === '\n') out += '\\n';
      else if (c === '\t') out += '\\t';
      else if (c === '\r') out += '\\r';
      else out += c;
    }
    return q + out + q;
  }

  function validateMatch(match, where, ri, errors) {
    function add(field, short) { errors.push({ msg: where + ': ' + short, short: short, rule: ri, field: field }); }
    if (!isMap(match) || Object.keys(match).length === 0) {
      add('match', "'match' must be a non-empty mapping");
      return;
    }
    Object.keys(match).forEach(function (key) {
      var value = match[key];
      var field = 'match.' + key;
      if (!has(MATCH_KEYS, key)) {
        add('match', "unknown match key '" + key + "'");
      } else if (has(LIST_MATCH_KEYS, key)) {
        if (!Array.isArray(value) || value.length === 0 || !value.every(nonemptyStr)) {
          add(field, "'" + key + "' must be a non-empty list of non-empty strings");
        } else if (key === 'language_in') {
          for (var i = 0; i < value.length; i++) {
            if (root.SpotiLang.normalize(value[i]) === null) {
              add(field, 'unknown language ' + pyRepr(value[i]) + " in 'language_in' (e.g. " +
                root.SpotiLang.CANONICAL.slice(0, 6).join(', ') + ', or an ISO code)');
              break;
            }
          }
        }
      } else if (has(INT_MATCH_KEYS, key)) {
        if (!isInt(value) || value < 1 || value > 9999) add(field, "'" + key + "' must be a year (integer 1-9999)");
      } else if (has(STR_MATCH_KEYS, key)) {
        if (!nonemptyStr(value)) add(field, "'" + key + "' must be a non-empty string");
      } else if (typeof value !== 'boolean') {
        add(field, "'" + key + "' must be true or false");
      }
    });
  }

  function validateRule(raw, index, errors) {
    if (!isMap(raw)) {
      errors.push({ msg: 'rules[' + index + ']: must be a mapping', short: 'must be a mapping', rule: index, field: null });
      return null;
    }
    var name = raw.name;
    var where = nonemptyStr(name) ? 'rules[' + index + '] (' + pyRepr(name) + ')' : 'rules[' + index + ']';
    function add(field, short) { errors.push({ msg: where + ': ' + short, short: short, rule: index, field: field }); }

    if (!nonemptyStr(name)) add('name', "'name' is required and must be a non-empty string");
    Object.keys(raw).forEach(function (key) {
      if (!has(RULE_KEYS, key)) add(null, "unknown key '" + key + "'");
    });
    if (!nonemptyStr(raw.target_playlist)) add('target_playlist', "'target_playlist' is required and must be a non-empty string");
    var enabled = 'enabled' in raw ? raw.enabled : true;
    if (typeof enabled !== 'boolean') add('enabled', "'enabled' must be true or false");
    var create = 'create_missing_playlists' in raw ? raw.create_missing_playlists : false;
    if (typeof create !== 'boolean') add('create_missing_playlists', "'create_missing_playlists' must be true or false");
    var days = raw.days_threshold;
    if (days !== undefined && days !== null && (!isInt(days) || days < 0)) {
      add('days_threshold', "'days_threshold' must be an integer >= 0");
    }
    validateMatch(raw.match, where, index, errors);
    return nonemptyStr(name) ? name : null;
  }

  // data: an already-parsed document (what yaml.safe_load would return). Returns {errors: [...]}.
  function validateConfig(data) {
    var errors = [];
    function top(field, msg, extra) {
      var e = { msg: msg, short: msg, rule: null, field: field };
      if (extra) for (var k in extra) e[k] = extra[k];
      errors.push(e);
    }
    if (data === null || data === undefined) data = {};
    if (!isMap(data)) return { errors: [{ msg: 'top level must be a mapping', short: 'top level must be a mapping', rule: null, field: null }] };

    Object.keys(data).forEach(function (key) {
      if (!has(TOP_LEVEL_KEYS, key)) top(null, "unknown top-level key '" + key + "'");
    });

    var days = 'default_days_threshold' in data ? data.default_days_threshold : 14;
    if (!isInt(days) || days < 0) top('default_days_threshold', "'default_days_threshold' must be an integer >= 0");
    var fallback = data.fallback_playlist;
    if (fallback !== undefined && fallback !== null && !nonemptyStr(fallback)) {
      top('fallback_playlist', "'fallback_playlist' must be a playlist name or null");
    }

    var lp = 'language_playlists' in data ? data.language_playlists : {};
    if (lp === null) lp = {};
    if (!isMap(lp)) {
      top('language_playlists', "'language_playlists' must be a mapping of playlist name -> language");
    } else {
      Object.keys(lp).forEach(function (name) {
        var lang = lp[name];
        var canon = root.SpotiLang.normalize(lang);
        if (!nonemptyStr(name)) {
          top('language_playlists', "'language_playlists': playlist names must be non-empty strings", { lpName: name });
        } else if (canon === null) {
          top('language_playlists', "'language_playlists' (" + pyRepr(name) + '): unknown language ' + pyRepr(lang),
            { lpName: name, short: 'unknown language ' + pyRepr(lang) });
        }
      });
    }

    var enrich = 'enrichment' in data ? data.enrichment : {};
    if (enrich === null) enrich = {};
    if (!isMap(enrich)) {
      top('enrichment', "'enrichment' must be a mapping");
    } else {
      Object.keys(enrich).forEach(function (key) {
        if (!has(ENRICHMENT_KEYS, key)) top('enrichment', "unknown key 'enrichment." + key + "'");
      });
      if ('musicbrainz' in enrich && typeof enrich.musicbrainz !== 'boolean') {
        top('enrichment.musicbrainz', "'enrichment.musicbrainz' must be true or false");
      }
      if ('english_default' in enrich && typeof enrich.english_default !== 'boolean') {
        top('enrichment.english_default', "'enrichment.english_default' must be true or false");
      }
    }

    var rawRules = 'rules' in data ? data.rules : [];
    if (!Array.isArray(rawRules)) {
      top('rules', "'rules' must be a list");
    } else {
      var seen = {};
      rawRules.forEach(function (raw, i) {
        var before = errors.length;
        var name = validateRule(raw, i, errors);
        if (errors.length > before || name === null) return;
        var folded = name.toLowerCase();
        if (Object.prototype.hasOwnProperty.call(seen, folded)) {
          errors.push({ msg: 'rules[' + i + '] (' + pyRepr(name) + '): duplicate rule name', short: 'duplicate rule name', rule: i, field: 'name' });
        }
        seen[folded] = true;
      });
    }
    return { errors: errors };
  }

  root.SpotiValidate = {
    validateConfig: validateConfig,
    MATCH_KEYS: MATCH_KEYS,
    LIST_MATCH_KEYS: LIST_MATCH_KEYS,
    INT_MATCH_KEYS: INT_MATCH_KEYS,
    STR_MATCH_KEYS: STR_MATCH_KEYS,
    BOOL_MATCH_KEYS: BOOL_MATCH_KEYS
  };
})(typeof window !== 'undefined' ? window : globalThis);
