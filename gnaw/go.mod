module github.com/Contextualist/grain/gnaw

go 1.17

replace (
	github.com/Contextualist/grain/gnaw/core => ./core
	github.com/Contextualist/grain/gnaw/transport => ./transport
)

require (
	github.com/gofrs/flock v0.8.1
	github.com/rs/zerolog v1.23.0
	github.com/tinylib/msgp v1.1.6
	golang.org/x/sys v0.0.0-20211103235746-7861aae1554b
)

require (
	github.com/philhofer/fwd v1.1.1 // indirect
	gopkg.in/check.v1 v1.0.0-20201130134442-10cb98267c6c // indirect
)
