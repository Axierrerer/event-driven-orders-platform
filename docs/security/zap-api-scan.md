# ZAP Scanning Report

ZAP by [Checkmarx](https://checkmarx.com/).


## Summary of Alerts

| Risk Level | Number of Alerts |
| --- | --- |
| High | 0 |
| Medium | 0 |
| Low | 1 |
| Informational | 5 |




## Insights

| Level | Reason | Site | Description | Statistic |
| --- | --- | --- | --- | --- |
| Low | Warning |  | ZAP warnings logged - see the zap.log file for details | 45    |
| Low | Exceeded High | http://host.docker.internal:8000 | Percentage of responses with status code 4xx | 97 % |
| Info | Informational | http://host.docker.internal | Percentage of responses with status code 4xx | 100 % |
| Info | Informational | http://host.docker.internal | Percentage of endpoints with method GET | 100 % |
| Info | Informational | http://host.docker.internal | Count of total endpoints | 1    |
| Info | Informational | http://host.docker.internal:8000 | Percentage of responses with status code 2xx | 2 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type application/json | 95 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type application/problem+json | 2 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with method DELETE | 3 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with method GET | 59 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with method PATCH | 3 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with method POST | 29 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with method PUT | 3 % |
| Info | Informational | http://host.docker.internal:8000 | Count of total endpoints | 81    |







## Alerts

| Name | Risk Level | Number of Instances |
| --- | --- | --- |
| Cross-Origin-Resource-Policy Header Missing or Invalid | Low | 5 |
| A Client Error response code was returned by the server | Informational | 85 |
| Authentication Request Identified | Informational | 1 |
| Information Disclosure - Sensitive Information in URL | Informational | 3 |
| Non-Storable Content | Informational | Systemic |
| Storable and Cacheable Content | Informational | 2 |




## Alert Detail



### [ Cross-Origin-Resource-Policy Header Missing or Invalid ](https://www.zaproxy.org/docs/alerts/90004/)



##### Low (Medium)

### Description

Cross-Origin-Resource-Policy header is an opt-in header designed to counter side-channels attacks like Spectre. Resource should be specifically set as shareable amongst different origins.

* URL: http://host.docker.internal:8000/api/v1/auth/.well-known/jwks.json
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/.well-known/jwks.json`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/categories
  * Node Name: `http://host.docker.internal:8000/api/v1/categories`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/openapi.json
  * Node Name: `http://host.docker.internal:8000/openapi.json`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/logout
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/logout ()({refresh_token})`
  * Method: `POST`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/resend-verification
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/resend-verification ()({email})`
  * Method: `POST`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 5

### Solution

Ensure that the application/web server sets the Cross-Origin-Resource-Policy header appropriately, and that it sets the Cross-Origin-Resource-Policy header to 'same-origin' for all web pages.
'same-site' is considered as less secured and should be avoided.
If resources must be shared, set the header to 'cross-origin'.
If possible, ensure that the end user uses a standards-compliant and modern web browser that supports the Cross-Origin-Resource-Policy header (https://caniuse.com/mdn-http_headers_cross-origin-resource-policy).

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 14

#### Source ID: 3

### [ A Client Error response code was returned by the server ](https://www.zaproxy.org/docs/alerts/100000/)



##### Informational (High)

### Description

A response code of 422 was returned by the server.
This may indicate that the application is failing to handle unexpected input correctly.
Raised by the 'Alert on HTTP Response Code Error' script

* URL: http://host.docker.internal:8000/api/v1/categories/category_id
  * Node Name: `http://host.docker.internal:8000/api/v1/categories/category_id`
  * Method: `DELETE`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id`
  * Method: `DELETE`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/user_id
  * Node Name: `http://host.docker.internal:8000/api/v1/users/user_id`
  * Method: `DELETE`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal/openapi.json
  * Node Name: `http://host.docker.internal/openapi.json`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/
  * Node Name: `http://host.docker.internal:8000/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/6123468004806770783
  * Node Name: `http://host.docker.internal:8000/6123468004806770783`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api
  * Node Name: `http://host.docker.internal:8000/api`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/
  * Node Name: `http://host.docker.internal:8000/api/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/6872781078332728717
  * Node Name: `http://host.docker.internal:8000/api/6872781078332728717`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/
  * Node Name: `http://host.docker.internal:8000/api/v1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/2414157224022181265
  * Node Name: `http://host.docker.internal:8000/api/v1/2414157224022181265`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth
  * Node Name: `http://host.docker.internal:8000/api/v1/auth`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/.well-known
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/.well-known`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/.well-known/
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/.well-known/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/.well-known/2224814052018302109
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/.well-known/2224814052018302109`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/2850632495732769347
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/2850632495732769347`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/actuator/health
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/actuator/health`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/categories/1532630365408124661
  * Node Name: `http://host.docker.internal:8000/api/v1/categories/1532630365408124661`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/5115899015287380798
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/5115899015287380798`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/stock
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/stock`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/stock/
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/stock/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/stock/8217927730902275885
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/stock/8217927730902275885`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/stock/product_id
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/stock/product_id`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/stock/product_id/2586066687019277172
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/stock/product_id/2586066687019277172`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications%3Fuser_id=&status=&limit=50&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications (limit,offset,status,user_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications/6552161341233426756
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications/6552161341233426756`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications/templates
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications/templates`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications/templates/5718684854668075152
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications/templates/5718684854668075152`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications/templates/key
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications/templates/key`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders
  * Node Name: `http://host.docker.internal:8000/api/v1/orders`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders%3Fstatus=&user_id=&limit=20&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/orders (limit,offset,status,user_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/6988575504865683291
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/6988575504865683291`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/order_id
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/order_id`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/order_id/5349222987284103558
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/order_id/5349222987284103558`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products%3Fq=&category=&price_min=&price_max=&sort=relevance&limit=20&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/products (category,limit,offset,price_max,price_min,q,sort)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/848369542712245227
  * Node Name: `http://host.docker.internal:8000/api/v1/products/848369542712245227`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id/557608828819357479
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id/557608828819357479`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users
  * Node Name: `http://host.docker.internal:8000/api/v1/users`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users%3Femail=zaproxy@example.com&limit=20&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/users (email,limit,offset)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/6553627760525709077
  * Node Name: `http://host.docker.internal:8000/api/v1/users/6553627760525709077`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/me
  * Node Name: `http://host.docker.internal:8000/api/v1/users/me`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/user_id
  * Node Name: `http://host.docker.internal:8000/api/v1/users/user_id`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/user_id/3388832411319983251
  * Node Name: `http://host.docker.internal:8000/api/v1/users/user_id/3388832411319983251`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/openapi.json/
  * Node Name: `http://host.docker.internal:8000/openapi.json/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/categories/category_id
  * Node Name: `http://host.docker.internal:8000/api/v1/categories/category_id ()({"name":ZAP,"description":Zaproxy alias impedit expedita quisquam pariatur exercitationem. Nemo rerum eveniet dolores rem quia dignissimos.})`
  * Method: `PATCH`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id ()({"sku":"John Doe","name":ZAP,"description":Zaproxy alias impedit expedita quisquam pariatur exercitationem. Nemo rerum eveniet dolores rem quia dignissimos.,"category_id":"John Doe","price":1.2,"currency":"John Doe","attributes":{"John Doe":"John Doe"},"images":["John Doe"]})`
  * Method: `PATCH`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/me
  * Node Name: `http://host.docker.internal:8000/api/v1/users/me ()({full_name,phone,address})`
  * Method: `PATCH`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/login
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/login ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/login
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/login ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/login
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/login ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/logout
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/logout ()({refresh_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/password
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/password ()({old_password,new_password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/refresh
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/refresh ()({refresh_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/refresh
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/refresh ()({refresh_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/register
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/register ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `409`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/register
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/register ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/resend-verification
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/resend-verification ()({email})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/verify-email
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/verify-email ()({token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/verify-email
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/verify-email ()({token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `422`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/categories
  * Node Name: `http://host.docker.internal:8000/api/v1/categories ()({name,description})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/inventory/stock/product_id/adjust
  * Node Name: `http://host.docker.internal:8000/api/v1/inventory/stock/product_id/adjust ()({delta,reason})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders
  * Node Name: `http://host.docker.internal:8000/api/v1/orders ()({items:[{product_id,quantity}]})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/order_id/cancel
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/order_id/cancel ()({John Doe})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/order_id/complete
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/order_id/complete`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/order_id/pay
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/order_id/pay`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/orders/order_id/ship
  * Node Name: `http://host.docker.internal:8000/api/v1/orders/order_id/ship`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products
  * Node Name: `http://host.docker.internal:8000/api/v1/products ()({sku,name,description,category_id,price,currency,attributes:{John Doe},images:[],is_published})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id/publish
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id/publish`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id/unpublish
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id/unpublish`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/computeMetadata/v1/
  * Node Name: `http://host.docker.internal:8000/computeMetadata/v1/ ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/latest/meta-data/
  * Node Name: `http://host.docker.internal:8000/latest/meta-data/ ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/metadata/instance
  * Node Name: `http://host.docker.internal:8000/metadata/instance ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/metadata/v1
  * Node Name: `http://host.docker.internal:8000/metadata/v1 ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/opc/v1/instance/
  * Node Name: `http://host.docker.internal:8000/opc/v1/instance/ ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/opc/v2/instance/
  * Node Name: `http://host.docker.internal:8000/opc/v2/instance/ ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/openstack/latest/meta_data.json
  * Node Name: `http://host.docker.internal:8000/openstack/latest/meta_data.json ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/notifications/templates/key
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications/templates/key ()({subject,body_html,body_text,locale})`
  * Method: `PUT`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/products/product_id
  * Node Name: `http://host.docker.internal:8000/api/v1/products/product_id ()({sku,name,description,category_id,price,currency,attributes:{John Doe},images:[]})`
  * Method: `PUT`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/users/user_id/roles
  * Node Name: `http://host.docker.internal:8000/api/v1/users/user_id/roles ()({roles:[]})`
  * Method: `PUT`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``


Instances: 85

### Solution



### Reference



#### CWE Id: [ 388 ](https://cwe.mitre.org/data/definitions/388.html)


#### WASC Id: 20

#### Source ID: 4

### [ Authentication Request Identified ](https://www.zaproxy.org/docs/alerts/10111/)



##### Informational (High)

### Description

The given request has been identified as an authentication request. The 'Other Info' field contains a set of key=value lines which identify any relevant fields. If the request is in a context which has an Authentication Method set to "Auto-Detect" then this rule will change the authentication to match the request identified.

* URL: http://host.docker.internal:8000/api/v1/auth/login
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/login ()({email,password})`
  * Method: `POST`
  * Parameter: `email`
  * Attack: ``
  * Evidence: `password`
  * Other Info: `userParam=email
userValue=zaproxy@example.com
passwordParam=password`


Instances: 1

### Solution

This is an informational alert rather than a vulnerability and so there is nothing to fix.

### Reference


* [ https://www.zaproxy.org/docs/desktop/addons/authentication-helper/auth-req-id/ ](https://www.zaproxy.org/docs/desktop/addons/authentication-helper/auth-req-id/)



#### Source ID: 3

### [ Information Disclosure - Sensitive Information in URL ](https://www.zaproxy.org/docs/alerts/10024/)



##### Informational (Medium)

### Description

The request appeared to contain sensitive information leaked in the URL. This can violate PCI and most organizational compliance policies. You can configure the list of strings for this check to add or remove values specific to your environment.

* URL: http://host.docker.internal:8000/api/v1/notifications%3Fuser_id=&status=&limit=50&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/notifications (limit,offset,status,user_id)`
  * Method: `GET`
  * Parameter: `user_id`
  * Attack: ``
  * Evidence: `user_id`
  * Other Info: `The URL contains potentially sensitive information. The following string was found via the pattern: user
user_id`
* URL: http://host.docker.internal:8000/api/v1/orders%3Fstatus=&user_id=&limit=20&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/orders (limit,offset,status,user_id)`
  * Method: `GET`
  * Parameter: `user_id`
  * Attack: ``
  * Evidence: `user_id`
  * Other Info: `The URL contains potentially sensitive information. The following string was found via the pattern: user
user_id`
* URL: http://host.docker.internal:8000/api/v1/users%3Femail=zaproxy@example.com&limit=20&offset=0
  * Node Name: `http://host.docker.internal:8000/api/v1/users (email,limit,offset)`
  * Method: `GET`
  * Parameter: `email`
  * Attack: ``
  * Evidence: `zaproxy@example.com`
  * Other Info: `The URL contains email address(es).`


Instances: 3

### Solution

Do not pass sensitive information in URIs.

### Reference



#### CWE Id: [ 598 ](https://cwe.mitre.org/data/definitions/598.html)


#### WASC Id: 13

#### Source ID: 3

### [ Non-Storable Content ](https://www.zaproxy.org/docs/alerts/10049/)



##### Informational (Medium)

### Description

The response contents are not storable by caching components such as proxy servers. If the response does not contain sensitive, personal or user-specific information, it may benefit from being stored and cached, to improve performance.

* URL: http://host.docker.internal:8000/api/v1/users/me
  * Node Name: `http://host.docker.internal:8000/api/v1/users/me`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/login
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/login ()({email,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/password
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/password ()({old_password,new_password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/refresh
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/refresh ()({refresh_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://host.docker.internal:8000/api/v1/auth/resend-verification
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/resend-verification ()({email})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `202`
  * Other Info: ``

Instances: Systemic


### Solution

The content may be marked as storable by ensuring that the following conditions are satisfied:
The request method must be understood by the cache and defined as being cacheable ("GET", "HEAD", and "POST" are currently defined as cacheable)
The response status code must be understood by the cache (one of the 1XX, 2XX, 3XX, 4XX, or 5XX response classes are generally understood)
The "no-store" cache directive must not appear in the request or response header fields
For caching by "shared" caches such as "proxy" caches, the "private" response directive must not appear in the response
For caching by "shared" caches such as "proxy" caches, the "Authorization" header field must not appear in the request, unless the response explicitly allows it (using one of the "must-revalidate", "public", or "s-maxage" Cache-Control response directives)
In addition to the conditions above, at least one of the following conditions must also be satisfied by the response:
It must contain an "Expires" header field
It must contain a "max-age" response directive
For "shared" caches such as "proxy" caches, it must contain a "s-maxage" response directive
It must contain a "Cache Control Extension" that allows it to be cached
It must have a status code that is defined as cacheable by default (200, 203, 204, 206, 300, 301, 404, 405, 410, 414, 501).

### Reference


* [ https://datatracker.ietf.org/doc/html/rfc7234 ](https://datatracker.ietf.org/doc/html/rfc7234)
* [ https://datatracker.ietf.org/doc/html/rfc7231 ](https://datatracker.ietf.org/doc/html/rfc7231)
* [ https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html ](https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html)


#### CWE Id: [ 524 ](https://cwe.mitre.org/data/definitions/524.html)


#### WASC Id: 13

#### Source ID: 3

### [ Storable and Cacheable Content ](https://www.zaproxy.org/docs/alerts/10049/)



##### Informational (Medium)

### Description

The response contents are storable by caching components such as proxy servers, and may be retrieved directly from the cache, rather than from the origin server by the caching servers, in response to similar requests from other users. If the response data is sensitive, personal or user-specific, this may result in sensitive information being leaked. In some cases, this may even result in a user gaining complete control of the session of another user, depending on the configuration of the caching components in use in their environment. This is primarily an issue where "shared" caching servers such as "proxy" caches are configured on the local network. This configuration is typically found in corporate or educational environments, for instance.

* URL: http://host.docker.internal:8000/api/v1/auth/.well-known/jwks.json
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/.well-known/jwks.json`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: `In the absence of an explicitly specified caching lifetime directive in the response, a liberal lifetime heuristic of 1 year was assumed. This is permitted by rfc7234.`
* URL: http://host.docker.internal:8000/api/v1/auth/logout
  * Node Name: `http://host.docker.internal:8000/api/v1/auth/logout ()({refresh_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: `In the absence of an explicitly specified caching lifetime directive in the response, a liberal lifetime heuristic of 1 year was assumed. This is permitted by rfc7234.`


Instances: 2

### Solution

Validate that the response does not contain sensitive, personal or user-specific information. If it does, consider the use of the following HTTP response headers, to limit, or prevent the content being stored and retrieved from the cache by another user:
Cache-Control: no-cache, no-store, must-revalidate, private
Pragma: no-cache
Expires: 0
This configuration directs both HTTP 1.0 and HTTP 1.1 compliant caching servers to not store the response, and to not retrieve the response (without validation) from the cache, in response to a similar request.

### Reference


* [ https://datatracker.ietf.org/doc/html/rfc7234 ](https://datatracker.ietf.org/doc/html/rfc7234)
* [ https://datatracker.ietf.org/doc/html/rfc7231 ](https://datatracker.ietf.org/doc/html/rfc7231)
* [ https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html ](https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html)


#### CWE Id: [ 524 ](https://cwe.mitre.org/data/definitions/524.html)


#### WASC Id: 13

#### Source ID: 3


