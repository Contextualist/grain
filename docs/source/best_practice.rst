Best practice
=============

Manage sessions with Linux's ``screen`` command
-----------------------------------------------

Running short test Grain sessions on your terminal can be a good start, but if you want to
keep the session running for a bit longer and check back later, ``screen`` is your friend.
With ``screen``, you can create and manage virtual terminals, which persist even after you log out from your main terminal.
You can even create multiple virtual terminals and switch among them: useful for running multiple Grain sessions concurrently.
To start a new session, do

.. code-block:: none

    screen -S mysession

You are now in a new screen session, and you can run commands as you usually do. (e.g. start a head process within)
To detach from the current session, press ``Ctrl-a`` then followed by ``d``.
To reattach the session at any time

.. code-block:: none

    screen -r mysession

In a screen session, when you are done, simply ``Ctrl-d`` to log out as usual.

You can create multiple screen sessions; just run ``screen -S`` with different names.
To list all running screen sessions, do

.. code-block:: none

    screen -list

Because all screen sessions live on the same host, sharing the scheduler among multiple Grain sessions becomes easy.
Recall that Grain head processes running on the same host with the same ``head.listen`` address will attach to the same scheduler.


Quickly switch between different Grain configs
----------------------------------------------

If environment variable ``GRAIN_CONFIG`` is set, Grain will look for the config file specified by it.
We can take advantage of this setting and specify different configs for different environments.
For example, if you have a project to be run on two different supercomputing clusters, A and B,
you can put config files ``grain.a.toml`` and ``grain.b.toml`` in the project directory.
Then, you can set environment variable ``GRAIN_CONFIG`` to ``grain.a.toml`` on cluster A's login profile, and ``grain.b.toml`` on cluster B's login profile.
In this way, Grain will look for the right config file regardless of the cluster you are currently logged into.

