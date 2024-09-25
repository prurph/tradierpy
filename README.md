# tradierpy

Limited Python wrapper around the [Tradier](https://documentation.tradier.com/brokerage-api) brokerage API

## Disclaimer

You probably don't want to use this. I pulled it out of one personal project so I could use it in another, and its scope is restricted to the parts of the Tradier API I actually use.

That said, PRs are always welcome. 😊

## Usage

- Init the client with account id and access token, or set the environment variables:
    - `TRADIER_ACCOUNT_ID`
    - `TRADIER_ACCESS_TOKEN`
- [python-dotenv](https://github.com/theskumar/python-dotenv) is recommended for env vars