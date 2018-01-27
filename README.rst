Self Hosted Docs
################

.. code-block:: text/x-nginx-conf

    server {
        listen      80;
        server_name your.docs.domain;
        charset     utf-8;
        include gzip.conf;

        # alias favicon.* to static
        location ~ ^/favicon.(\w*)$ {
            include static_limit;
            alias /path/to/your/favicon.$1;
        }

        # Finally, send all non-media requests to the Django server.
        location = / {
            alias /srv/http/docs/;
        }

        location ~* /([^/]+)/(.*) {
            alias /srv/http/docs/$1/docs/_build/html/$2;
        }
    }
