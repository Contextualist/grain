module github.com/Contextualist/grain/gnaw

go 1.17

replace (
	github.com/Contextualist/grain/gnaw/core => ./core
	github.com/Contextualist/grain/gnaw/transport => ./transport
)

require (
	github.com/rs/zerolog v1.23.0
	github.com/tinylib/msgp v1.1.6
	golang.org/x/sys v0.0.0-20210525143221-35b2ab0089ea
)

require github.com/philhofer/fwd v1.1.1 // indirect
