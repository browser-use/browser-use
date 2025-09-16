# diff

implementation of myers diff algorithm

[![Build Status](https://travis-ci.org/Swatinem/diff.png?branch=master)](https://travis-ci.org/Swatinem/diff)
[![Coverage Status](https://coveralls.io/repos/Swatinem/diff/badge.png?branch=master)](https://coveralls.io/r/Swatinem/diff)
[![Dependency Status](https://gemnasium.com/Swatinem/diff.png)](https://gemnasium.com/Swatinem/diff)


This uses the [*An O(ND) Difference Algorithm and Its Variations*](http://www.xmailserver.org/diff2.pdf)
Also see http://simplygenius.net/Article/DiffTutorial2 and
http://www.mathertel.de/Diff/ViewSrc.aspx for more inspiration

## Installation

    $ npm install diff
    $ component install Swatinem/diff

## Usage

### diff(a, b, [eql(a, b)])

Given two arrays (or array-likes, such as strings) `a` and `b` and an optional
equal function `eql`, this will return an array with the following operations:
* *nop* the element is in both arrays
* *ins* the element is only in array `b` and will be inserted
* *del* the element in only in array `a` and will be removed
* *rep* the element from `a` will be replaced by the element from `b`.
This is essentially the same as a del+ins

## License

  LGPLv3

