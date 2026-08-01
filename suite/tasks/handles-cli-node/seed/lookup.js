// Looks up an Ada Handle and prints its Cardano address.
//
// Uses the `request` package, which was deprecated in 2020 and is no longer maintained.
const request = require('request');

const HANDLE = process.argv[2] || 'goose';

request(
  { url: 'https://api.handle.me/handles/' + HANDLE, json: true },
  function (err, res, body) {
    if (err) {
      console.log('request failed: ' + err.message);
      return;
    }
    if (res.statusCode !== 200) {
      console.log('lookup failed with status ' + res.statusCode);
      return;
    }
    console.log('address: ' + body.resolved_addresses.ada);
  }
);
